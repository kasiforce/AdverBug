#!/usr/bin/env python3
"""Select Java production files as file-level test-generation targets.

The five selection predicates are conjunctive:

* file NLOC >= 200;
* concrete method count >= 5;
* callable entry count >= 2;
* aggregate cyclomatic complexity >= 30;
* statically resolved cross-file project-internal method fan-out >= 5.

NLOC and cyclomatic complexity use Lizard. Java declarations and call sites use
the repository's Tree-sitter based extractors. Cross-file fan-out counts unique
resolved production method definitions, never call-site occurrences.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import lizard


REPO_ROOT = Path(__file__).resolve().parents[1]
EXTRACT_ROOT = REPO_ROOT / "extract_functions"
if str(EXTRACT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXTRACT_ROOT))

from java_extra import JavaProjectTestScopeExtractor, discover_java_files  # noqa: E402
from extract_func import (  # noqa: E402
    _call_resolves_to_definition,
    _file_imports_target,
    _java_same_package,
    _narrow_by_arity,
    _visible_imports,
    build_repository_index,
)
from callable_utils import has_nonempty_callable_body  # noqa: E402


def _relative(path: str | Path, root: Path) -> str:
    return Path(path).resolve().relative_to(root).as_posix()


def _file_method_metrics(repo: Path, java_files: list[str]) -> dict[str, dict[str, Any]]:
    extractor = JavaProjectTestScopeExtractor(
        project_root=str(repo),
        file_list=java_files,
        min_loc_threshold=0,
        min_complexity_threshold=0,
        min_outgoing_degree_threshold=0,
    )
    extractor._parse_project()

    result: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "concrete_method_count": 0,
            "callable_entry_count": 0,
            "total_cyclomatic_complexity": 0,
        }
    )
    for class_info in extractor.classes.values():
        class_is_private = class_info.get("is_effectively_private", False)
        for method in class_info["methods"].values():
            # Abstract declarations have no executable body and are not concrete methods.
            if method.get("is_abstract", False) or not has_nonempty_callable_body(
                method.get("code", ""), "java"
            ):
                continue
            rel = _relative(method["src_file"], repo)
            metrics = result[rel]
            metrics["concrete_method_count"] += 1
            metrics["total_cyclomatic_complexity"] += int(method.get("complexity", 1))
            if not class_is_private and not method.get("is_private", False):
                metrics["callable_entry_count"] += 1
    return result


def _resolved_cross_file_fanout(
    index: dict[str, Any], production_paths: set[str], language: str = "java",
    source_paths: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    functions_by_id = index["functions_by_id"]
    definitions_by_name = index["by_name"]
    output: dict[str, dict[str, Any]] = {}
    java_visibility_cache: dict[tuple[str, str], bool] = {}
    resolution_cache: dict[tuple[str, str, str, str], bool] = {}

    callers_by_file: dict[str, list[Any]] = defaultdict(list)
    for function in index["functions"]:
        if function.language == language and function.path in production_paths:
            callers_by_file[function.path].append(function)

    for source_file in sorted(source_paths if source_paths is not None else production_paths):
        resolved: dict[str, Any] = {}
        unresolved_project_calls = 0
        unresolved_cross_file_calls = 0
        unresolved_cross_file_candidate_details = []
        total_calls = 0
        for caller in callers_by_file.get(source_file, []):
            visible_imports = (
                _visible_imports(index, caller.path, caller.id)
                if language == "java"
                else []
            )
            for call in index["caller_calls"].get(caller.id, []):
                total_calls += 1
                candidates = [
                    definition
                    for definition in definitions_by_name.get((language, call.callee_name), [])
                    if definition.id != caller.id and definition.path in production_paths
                ]
                if language == "java":
                    # This is a conservative candidate prefilter, not a resolver:
                    # Java cross-file calls can only reach a same-package or
                    # imported declaration (same-file calls are retained so they
                    # can take precedence below). Exact receiver/overload checks
                    # are still performed by _call_resolves_to_definition.
                    visible_candidates = []
                    for definition in candidates:
                        cache_key = (caller.id, definition.id)
                        is_visible = java_visibility_cache.get(cache_key)
                        if is_visible is None:
                            is_visible = (
                                definition.path == caller.path
                                or _java_same_package(caller.path, definition.path, index)
                                or _file_imports_target(
                                    caller.path,
                                    visible_imports,
                                    definition,
                                    "java",
                                )
                            )
                            java_visibility_cache[cache_key] = is_visible
                        if is_visible:
                            visible_candidates.append(definition)
                    candidates = visible_candidates
                matching = []
                for definition in candidates:
                    resolution_key = (
                        caller.id,
                        call.callee_expression or call.callee_name,
                        call.syntax_kind,
                        definition.id,
                    )
                    matches = resolution_cache.get(resolution_key)
                    if matches is None:
                        matches = _call_resolves_to_definition(
                            call, caller, definition, index
                        )
                        resolution_cache[resolution_key] = matches
                    if matches:
                        matching.append(definition)
                local = [definition for definition in matching if definition.path == source_file]
                if local:
                    matching = local
                matching = _narrow_by_arity(call, matching)
                if len(matching) == 1:
                    definition = matching[0]
                    if definition.path != source_file:
                        resolved[definition.id] = definition
                elif candidates:
                    unresolved_project_calls += 1
                    unresolved_targets = matching or candidates
                    if any(
                        definition.path != source_file
                        for definition in unresolved_targets
                    ):
                        unresolved_cross_file_calls += 1
                        unresolved_cross_file_candidate_details.append({
                            "callee": call.callee_name,
                            "candidate_files": sorted({
                                definition.path
                                for definition in unresolved_targets
                                if definition.path != source_file
                            }),
                        })

        dependencies = sorted(
            (
                {
                    "file": definition.path,
                    "qualified_name": definition.qualified_name,
                    "start_line": definition.start_line,
                }
                for definition in resolved.values()
            ),
            key=lambda item: (item["file"], item["qualified_name"], item["start_line"]),
        )
        resolved_fanout = len(dependencies)
        output[source_file] = {
            "cross_file_internal_method_fanout": (
                resolved_fanout + unresolved_cross_file_calls
            ),
            "resolved_cross_file_internal_method_fanout": resolved_fanout,
            "unresolved_cross_file_candidate_call_sites": unresolved_cross_file_calls,
            "unresolved_cross_file_candidate_call_site_details": unresolved_cross_file_candidate_details,
            "cross_file_internal_file_fanout": len({item["file"] for item in dependencies}),
            "resolved_cross_file_dependencies": dependencies,
            "total_call_sites": total_calls,
            "unresolved_project_candidate_call_sites": unresolved_project_calls,
        }
    return output


def select_files(
    repo: Path,
    min_nloc: int,
    min_methods: int,
    min_entries: int,
    min_total_cc: int,
    min_cross_file_fanout: int,
) -> dict[str, Any]:
    repo = repo.resolve()
    java_files = discover_java_files(str(repo))
    production_paths = {_relative(path, repo) for path in java_files}
    method_metrics = _file_method_metrics(repo, java_files)
    index = build_repository_index(repo, allowed_files=production_paths)
    fanout_metrics = _resolved_cross_file_fanout(index, production_paths)

    thresholds = {
        "min_nloc": min_nloc,
        "min_concrete_methods": min_methods,
        "min_callable_entries": min_entries,
        "min_total_cyclomatic_complexity": min_total_cc,
        "min_cross_file_internal_method_fanout": min_cross_file_fanout,
    }
    records = []
    for absolute_path in java_files:
        rel = _relative(absolute_path, repo)
        report = lizard.analyze_file(absolute_path)
        nloc = int(getattr(report, "nloc", 0))
        metrics = {
            "nloc": nloc,
            **method_metrics.get(
                rel,
                {
                    "concrete_method_count": 0,
                    "callable_entry_count": 0,
                    "total_cyclomatic_complexity": 0,
                },
            ),
            **fanout_metrics.get(
                rel,
                {
                    "cross_file_internal_method_fanout": 0,
                    "resolved_cross_file_internal_method_fanout": 0,
                    "unresolved_cross_file_candidate_call_sites": 0,
                    "cross_file_internal_file_fanout": 0,
                    "resolved_cross_file_dependencies": [],
                    "total_call_sites": 0,
                    "unresolved_project_candidate_call_sites": 0,
                },
            ),
        }
        predicates = {
            "nloc": metrics["nloc"] >= min_nloc,
            "concrete_method_count": metrics["concrete_method_count"] >= min_methods,
            "callable_entry_count": metrics["callable_entry_count"] >= min_entries,
            "total_cyclomatic_complexity": metrics["total_cyclomatic_complexity"] >= min_total_cc,
            "cross_file_internal_method_fanout": (
                metrics["cross_file_internal_method_fanout"] >= min_cross_file_fanout
            ),
        }
        records.append(
            {
                "src_file": rel,
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
        "schema_version": 2,
        "project_root": str(repo),
        "selection_logic": "AND",
        "thresholds": thresholds,
        "metric_notes": {
            "nloc": "Lizard file-level non-comment lines of code.",
            "concrete_method_count": "Java methods with bodies; constructors excluded.",
            "callable_entry_count": "Non-private concrete methods in non-private classes.",
            "total_cyclomatic_complexity": "Sum of Lizard method-level CC in the file.",
            "cross_file_internal_method_fanout": "Unique resolved production methods in other project files plus unresolved call sites with cross-file project candidates.",
            "resolved_cross_file_internal_method_fanout": "Unique statically resolved production methods in other project files.",
            "unresolved_cross_file_candidate_call_sites": "Call sites that have cross-file project candidates but cannot be resolved to one definition; each site counts once.",
        },
        "production_file_count": len(java_files),
        "selected_file_count": len(selected),
        "selected_files": selected,
        "all_files": sorted(records, key=lambda record: record["src_file"]),
        "index_skipped": index.get("skipped", []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--min-nloc", type=int, default=200)
    parser.add_argument("--min-methods", type=int, default=5)
    parser.add_argument("--min-entries", type=int, default=2)
    parser.add_argument("--min-total-cc", type=int, default=100)
    parser.add_argument("--min-cross-file-fanout", type=int, default=5)
    args = parser.parse_args()

    result = select_files(
        args.repo,
        args.min_nloc,
        args.min_methods,
        args.min_entries,
        args.min_total_cc,
        args.min_cross_file_fanout,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Selected {result['selected_file_count']}/{result['production_file_count']} production files; "
        f"wrote {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
