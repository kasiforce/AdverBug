#!/usr/bin/env python3
"""Select real source directories using project-relative module metrics."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from extract_func import build_repository_index  # noqa: F401  # import path compatibility
from java_extra import discover_java_files
from js_extra import JSProjectTestScopeExtractor, discover_javascript_files
from py_extra import EnhancedPythonFocalExtractor, discover_python_files
from select_java_test_files import _file_method_metrics, _relative, _resolved_cross_file_fanout
from select_source_test_files import _lizard_metrics, _callable_entries


ALIASES = {"java": "java", "python": "python", "py": "python", "javascript": "javascript", "js": "javascript"}


def _test_module(module: str, language: str) -> str:
    parts = list(Path(module).parts)
    if language == "java":
        for index in range(len(parts) - 1):
            if parts[index] == "main" and parts[index + 1] == "java":
                parts[index] = "test"
                break
        return Path(*parts).as_posix()
    if language == "python":
        root = "test" if parts and parts[0] == "src" else "tests"
        relative_parts = parts[1:] if parts and parts[0] == "src" else parts
        return Path(root, *relative_parts).as_posix()
    return Path("test", *parts[1:] if parts and parts[0] == "src" else parts).as_posix()


def _discover(repo: Path, language: str) -> list[str]:
    if language == "java":
        return discover_java_files(str(repo))
    if language == "python":
        return discover_python_files(str(repo))
    return discover_javascript_files(str(repo))


def _file_metrics(repo: Path, files: list[str], language: str) -> dict[str, dict[str, int]]:
    metrics = _lizard_metrics(files, repo)
    if language == "java":
        for rel, values in _file_method_metrics(repo, files).items():
            metrics.setdefault(rel, {}).update(values)
    else:
        entries = _callable_entries(repo, files, language)
        for rel in metrics:
            metrics[rel]["callable_entry_count"] = entries.get(rel, 0)
    return metrics


def select_directory_modules(
    repo: Path,
    language: str,
    min_module_nloc: int = 500,
    min_cross_module_fanout: int = 3,
    min_total_cc: int = 100,
) -> dict[str, Any]:
    repo = repo.resolve()
    language = ALIASES[language.lower()]
    files = _discover(repo, language)
    metrics = _file_metrics(repo, files, language)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in files:
        rel = _relative(path, repo)
        directory = Path(rel).parent.as_posix()
        if directory != ".":
            groups[directory].append({"src_file": rel, **metrics.get(rel, {})})

    candidates = []
    for directory, records in groups.items():
        file_count = len(records)
        if 3 <= file_count <= 5:
            candidates.append({
                "target_type": "module",
                "module": directory,
                "test_module": _test_module(directory, language),
                "file_count": file_count,
                "nloc": sum(r.get("nloc", 0) for r in records),
                "concrete_method_count": sum(r.get("concrete_method_count", 0) for r in records),
                "callable_entry_count": sum(r.get("callable_entry_count", 0) for r in records),
                "total_cyclomatic_complexity": sum(r.get("total_cyclomatic_complexity", 0) for r in records),
                "files": sorted(r["src_file"] for r in records),
            })

    # Build the call index once, but resolve calls only from candidate-module
    # files; calls from other production files cannot affect module selection.
    production_paths = {_relative(path, repo) for path in files}
    candidate_source_paths = {
        source_file for record in candidates for source_file in record["files"]
    }
    index = build_repository_index(repo, allowed_files=production_paths)
    file_fanout = _resolved_cross_file_fanout(
        index, production_paths, language, source_paths=candidate_source_paths
    )

    # Count unique resolved target methods outside each directory, plus
    # unresolved call sites that have at least one candidate outside it.
    for record in candidates:
        module = record["module"]
        source_files = set(record["files"])
        resolved_targets = set()
        unresolved_external_sites = 0
        for source_file in source_files:
            details = file_fanout.get(source_file, {})
            for dependency in details.get("resolved_cross_file_dependencies", []):
                if Path(dependency["file"]).parent.as_posix() != module:
                    resolved_targets.add((dependency["file"], dependency["qualified_name"], dependency["start_line"]))
            for call in details.get("unresolved_cross_file_candidate_call_site_details", []):
                if any(Path(path).parent.as_posix() != module for path in call["candidate_files"]):
                    unresolved_external_sites += 1
        record["cross_module_fanout"] = len(resolved_targets) + unresolved_external_sites

    medians = {
        "nloc": statistics.median(r["nloc"] for r in candidates) if candidates else 0,
        "total_cyclomatic_complexity": statistics.median(
            r["total_cyclomatic_complexity"] for r in candidates
        ) if candidates else 0,
    }
    for record in candidates:
        predicates = {
            "file_count_3_to_5": 3 <= record["file_count"] <= 5,
            "callable_entry_count": record["callable_entry_count"] >= 2,
            "cross_module_fanout": record["cross_module_fanout"] >= min_cross_module_fanout,
            "total_cyclomatic_complexity": record["total_cyclomatic_complexity"] >= min_total_cc,
            "nloc": record["nloc"] >= min_module_nloc,
        }
        record["predicates"] = predicates
        record["selected"] = all(predicates.values())
    candidates.sort(key=lambda r: (-r["total_cyclomatic_complexity"], -r["nloc"], r["module"]))
    selected = [r for r in candidates if r["selected"]]
    return {
        "schema_version": 2,
        "language": language,
        "project_root": str(repo),
        "selection_logic": "AND",
        "thresholds": {
            "min_module_files": 3,
            "max_module_files": 5,
            "min_callable_entries": 2,
            "min_module_nloc": min_module_nloc,
            "min_cross_module_fanout": min_cross_module_fanout,
            "min_total_cyclomatic_complexity": min_total_cc,
            "project_candidate_module_nloc_median": medians["nloc"],
            "project_candidate_module_total_cyclomatic_complexity_median": medians["total_cyclomatic_complexity"],
        },
        "production_file_count": len(files),
        "candidate_module_count": len(candidates),
        "selected_module_count": len(selected),
        "selected_modules": selected,
        "all_candidate_modules": candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--language", required=True, choices=sorted(ALIASES))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--min-module-nloc", type=int, default=500)
    parser.add_argument("--min-cross-module-fanout", type=int, default=3)
    parser.add_argument("--min-total-cc", type=int, default=100)
    args = parser.parse_args()
    result = select_directory_modules(
        args.repo, args.language, args.min_module_nloc, args.min_cross_module_fanout,
        args.min_total_cc,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Selected {result['selected_module_count']}/{result['candidate_module_count']} modules; wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
