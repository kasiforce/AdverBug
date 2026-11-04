#!/usr/bin/env python3
"""Apply the same five file-level target predicates across supported languages."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import lizard

from extract_func import build_repository_index
from java_extra import discover_java_files, gen_test_file_path as gen_java_test_file_path
from js_extra import JSProjectTestScopeExtractor, discover_javascript_files, gen_test_file_path as gen_js_test_file_path
from py_extra import (
    EnhancedPythonFocalExtractor,
    discover_python_files,
    gen_test_file_path as gen_python_test_file_path,
)
from select_java_test_files import (
    _file_method_metrics,
    _relative,
    _resolved_cross_file_fanout,
)
from callable_utils import has_nonempty_callable_body


LANGUAGE_ALIASES = {
    "java": "java",
    "python": "python",
    "py": "python",
    "javascript": "javascript",
    "js": "javascript",
}


def _discover(repo: Path, language: str) -> list[str]:
    if language == "java":
        return discover_java_files(str(repo))
    if language == "python":
        return discover_python_files(str(repo))
    return discover_javascript_files(str(repo))


def _test_file(repo: Path, src_file: str, language: str) -> str:
    generators = {
        "java": gen_java_test_file_path,
        "python": gen_python_test_file_path,
        "javascript": gen_js_test_file_path,
    }
    return generators[language](str(repo), str(repo / src_file))


def _lizard_metrics(files: list[str], repo: Path) -> dict[str, dict[str, int]]:
    metrics = {}
    for path in files:
        report = lizard.analyze_file(path)
        functions = list(getattr(report, "function_list", []) or [])
        metrics[_relative(path, repo)] = {
            "nloc": int(getattr(report, "nloc", 0)),
            "concrete_method_count": len(functions),
            "total_cyclomatic_complexity": sum(
                int(getattr(function, "cyclomatic_complexity", 1))
                for function in functions
            ),
        }
    return metrics


def _callable_entries(repo: Path, files: list[str], language: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    if language == "python":
        # Callable-entry discovery only needs parsed definitions.  Set the
        # focal-function gates above every real value so the extractor does
        # not try to resolve project calls without a repository index.
        extractor = EnhancedPythonFocalExtractor(
            str(repo),
            files,
            min_loc_threshold=float("inf"),
            min_complexity_threshold=float("inf"),
            min_outgoing_degree_threshold=0,
        )
        for path in files:
            try:
                functions = extractor._extract_focal_method(path) or []
            except Exception:
                functions = []
            counts[_relative(path, repo)] = sum(
                1
                for function in functions
                if not function.get("name", "").startswith("_")
                and not re.search(
                    r"@\s*(?:abc\.)?abstractmethod\b", function.get("code", "")
                )
                and has_nonempty_callable_body(function.get("code", ""), "python")
            )
        return counts

    extractor = JSProjectTestScopeExtractor(
        str(repo), files, only_exported=True, min_project_functions=0
    )
    for path in files:
        try:
            functions = extractor._extract_functions_from_file(path) or []
        except Exception:
            functions = []
        counts[_relative(path, repo)] = sum(
            has_nonempty_callable_body(function.get("code", ""), "javascript")
            for function in functions
        )
    return counts


def select_files(
    repo: Path,
    language: str,
    min_nloc: int = 200,
    min_methods: int = 5,
    min_entries: int = 2,
    min_total_cc: int = 100,
    min_cross_file_fanout: int = 5,
) -> dict[str, Any]:
    repo = repo.resolve()
    language = LANGUAGE_ALIASES[language.lower()]
    files = _discover(repo, language)
    production_paths = {_relative(path, repo) for path in files}

    # NLOC is the first-stage filter. Compute it for every production file,
    # then avoid the more expensive entry/call analysis for smaller files.
    base_metrics = _lizard_metrics(files, repo)
    nloc_eligible_paths = {
        rel
        for rel, metrics in base_metrics.items()
        if metrics["nloc"] >= min_nloc
    }
    nloc_eligible_files = [
        path for path in files if _relative(path, repo) in nloc_eligible_paths
    ]

    if language == "java":
        method_metrics = (
            _file_method_metrics(repo, nloc_eligible_files)
            if nloc_eligible_files
            else {}
        )
        for rel in nloc_eligible_paths:
            base_metrics[rel].update(
                method_metrics.get(
                    rel,
                    {
                        "concrete_method_count": 0,
                        "callable_entry_count": 0,
                        "total_cyclomatic_complexity": 0,
                    },
                )
            )
    else:
        entries = (
            _callable_entries(repo, nloc_eligible_files, language)
            if nloc_eligible_files
            else {}
        )
        for rel in nloc_eligible_paths:
            metrics = base_metrics[rel]
            metrics["callable_entry_count"] = entries.get(rel, 0)

    # Once a file passes the project-relative NLOC gate, evaluate all remaining
    # metrics for it. Keep every production definition in the repository index
    # as a possible cross-file callee.
    fanout_source_paths = nloc_eligible_paths
    if fanout_source_paths:
        index = build_repository_index(repo, allowed_files=production_paths)
        fanout = _resolved_cross_file_fanout(
            index, production_paths, language, source_paths=fanout_source_paths
        )
    else:
        index = {"skipped": []}
        fanout = {}
    thresholds = {
        "min_nloc": min_nloc,
        "min_concrete_methods": min_methods,
        "min_callable_entries": min_entries,
        "min_total_cyclomatic_complexity": min_total_cc,
        "min_cross_file_internal_method_fanout": min_cross_file_fanout,
    }
    records = []
    for rel in sorted(production_paths):
        metrics = {
            **base_metrics.get(rel, {}),
            **fanout.get(rel, {}),
            "extended_metrics_evaluated": rel in nloc_eligible_paths,
            "cross_file_fanout_evaluated": rel in fanout_source_paths,
        }
        predicates = {
            "nloc": metrics.get("nloc", 0) >= min_nloc,
            "concrete_method_count": metrics.get("concrete_method_count", 0) >= min_methods,
            "callable_entry_count": metrics.get("callable_entry_count", 0) >= min_entries,
            "total_cyclomatic_complexity": metrics.get("total_cyclomatic_complexity", 0) >= min_total_cc,
            "cross_file_internal_method_fanout": (
                metrics.get("cross_file_internal_method_fanout", 0) >= min_cross_file_fanout
            ),
        }
        records.append(
            {
                "target_type": "source_file",
                "src_file": rel,
                "test_file": _test_file(repo, rel, language),
                **metrics,
                "predicates": predicates,
                "selected": all(predicates.values()),
            }
        )

    selected = sorted(
        (record for record in records if record["selected"]),
        key=lambda record: (
            -record["total_cyclomatic_complexity"],
            -record["cross_file_internal_method_fanout"],
            -record["nloc"],
            record["src_file"],
        ),
    )
    return {
        "schema_version": 5,
        "language": language,
        "project_root": str(repo),
        "selection_logic": "AND",
        "thresholds": thresholds,
        "metric_notes": {
            "nloc": "Lizard file-level NLOC; a file must meet the configured minimum before other metrics are evaluated.",
            "concrete_method_count": "Lizard-recognized concrete functions/methods; constructors excluded for Java.",
            "callable_entry_count": (
                "Non-empty, non-abstract test entries: Python public-by-naming-convention functions/methods; JavaScript exported functions and public methods of exported classes; Java non-private concrete methods."
            ),
            "total_cyclomatic_complexity": "Sum of Lizard function/method cyclomatic complexity.",
            "cross_file_internal_method_fanout": "Unique resolved production functions/methods in other project files plus unresolved call sites with cross-file project candidates.",
            "resolved_cross_file_internal_method_fanout": "Unique statically resolved production functions/methods in other project files.",
            "unresolved_cross_file_candidate_call_sites": "Call sites that have cross-file project candidates but cannot be resolved to one definition; each site counts once.",
        },
        "production_file_count": len(files),
        "selected_file_count": len(selected),
        "selected_files": selected,
        "all_files": records,
        "index_skipped": index.get("skipped", []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--language", required=True, choices=sorted(LANGUAGE_ALIASES))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--min-nloc", type=int, default=200)
    parser.add_argument("--min-methods", type=int, default=5)
    parser.add_argument("--min-entries", type=int, default=2)
    parser.add_argument("--min-total-cc", type=int, default=100)
    parser.add_argument("--min-cross-file-fanout", type=int, default=5)
    args = parser.parse_args()
    result = select_files(
        args.repo,
        args.language,
        min_nloc=args.min_nloc,
        min_methods=args.min_methods,
        min_entries=args.min_entries,
        min_total_cc=args.min_total_cc,
        min_cross_file_fanout=args.min_cross_file_fanout,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Selected {result['selected_file_count']}/{result['production_file_count']} files; wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
