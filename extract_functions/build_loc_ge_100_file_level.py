#!/usr/bin/env python3
"""Build runnable file-level targets from the loc_ge_100 function dataset."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from java_extra import gen_test_file_path as gen_java_test_file_path
from js_extra import gen_test_file_path as gen_js_test_file_path
from py_extra import gen_test_file_path as gen_python_test_file_path


LANGUAGES = ("java", "js", "python")
OUTPUT_LANGUAGES = {
    "java": "java",
    "js": "javascript",
    "python": "python",
}
TEST_PATH_GENERATORS = {
    "java": gen_java_test_file_path,
    "js": gen_js_test_file_path,
    "python": gen_python_test_file_path,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loc-dataset", type=Path, default=Path("dataset/loc_ge_100"))
    parser.add_argument("--file-metrics", type=Path, default=Path("dataset/file_level"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dataset/loc_ge_100_file_level_nloc300"),
    )
    parser.add_argument("--min-nloc", type=int, default=300)
    parser.add_argument("--min-functions", type=int, default=3)
    parser.add_argument("--min-callable-entries", type=int, default=1)
    parser.add_argument("--min-total-cyclomatic-complexity", type=int, default=0)
    parser.add_argument("--min-cross-file-internal-method-fanout", type=int, default=0)
    parser.add_argument(
        "--min-resolved-cross-file-internal-method-fanout", type=int, default=0
    )
    parser.add_argument(
        "--min-average-cyclomatic-complexity",
        type=float,
        default=0.0,
        help="Minimum total_cyclomatic_complexity / concrete_method_count.",
    )
    parser.add_argument(
        "--fallback-empty-projects",
        action="store_true",
        help=(
            "For a project with no eligible loc_ge_100 target file, select every production "
            "file that meets the size thresholds."
        ),
    )
    parser.add_argument(
        "--fallback-min-primary-files",
        type=int,
        default=1,
        help=(
            "When fallback is enabled, supplement projects having fewer than this many "
            "primary files with every other production file meeting the hard thresholds."
        ),
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=["packages/imba/src/compiler/nodes.mjs"],
        help="Repository-relative production path to exclude; repeat as needed.",
    )
    return parser.parse_args()


def load_function_targets(
    dataset_root: Path,
) -> tuple[
    dict[tuple[str, str, str], list[dict[str, Any]]],
    set[tuple[str, str]],
]:
    targets: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    projects: set[tuple[str, str]] = set()
    for language in LANGUAGES:
        for dataset_path in sorted((dataset_root / language).glob("*.json")):
            if dataset_path.stem.endswith("_specification"):
                continue
            projects.add((language, dataset_path.stem))
            records = json.loads(dataset_path.read_text(encoding="utf-8"))
            if not isinstance(records, list):
                raise ValueError(f"Expected a JSON array in {dataset_path}")
            for record in records:
                targets[(language, dataset_path.stem, record["src_file"])].append(record)
    return targets, projects


def load_file_metrics(
    metrics_root: Path,
    target_keys: set[tuple[str, str, str]],
    projects: set[tuple[str, str]],
    include_all_project_files: bool = False,
) -> tuple[
    dict[tuple[str, str, str], dict[str, Any]],
    dict[tuple[str, str], str],
]:
    metrics: dict[tuple[str, str, str], dict[str, Any]] = {}
    project_roots: dict[tuple[str, str], str] = {}
    for language, project in sorted(projects):
        metrics_path = metrics_root / language / f"{project}.json"
        payload = json.loads(metrics_path.read_text(encoding="utf-8"))
        project_roots[(language, project)] = payload["project_root"]
        for record in payload["all_files"]:
            key = (language, project, record["src_file"])
            if include_all_project_files or key in target_keys:
                metrics[key] = record
    missing = sorted(target_keys - metrics.keys())
    if missing:
        raise ValueError(f"Missing file metrics for {len(missing)} targets: {missing[:5]}")
    return metrics, project_roots


def compact_function_target(record: dict[str, Any]) -> dict[str, Any]:
    fields = ("name", "method_key", "start_line", "end_line", "loc", "complexity")
    return {field: record[field] for field in fields if record.get(field) is not None}


def build_entries(
    function_targets: dict[tuple[str, str, str], list[dict[str, Any]]],
    metrics: dict[tuple[str, str, str], dict[str, Any]],
    project_roots: dict[tuple[str, str], str],
    min_nloc: int,
    min_functions: int,
    min_total_cyclomatic_complexity: int,
    min_cross_file_internal_method_fanout: int,
    min_resolved_cross_file_internal_method_fanout: int,
    min_average_cyclomatic_complexity: float,
    excluded_paths: set[str],
    fallback_empty_projects: bool = False,
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    entries: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for (language, project, _), source_targets in function_targets.items():
        roots = {record["project_root"] for record in source_targets}
        if len(roots) != 1:
            raise ValueError(
                f"Inconsistent project roots for {(language, project)}: {sorted(roots)}"
            )
        root = roots.pop()
        existing = project_roots[(language, project)]
        if existing != root:
            raise ValueError(
                f"Inconsistent project roots for {(language, project)}: {existing!r}, {root!r}"
            )

    def make_entry(
        language: str,
        project: str,
        src_file: str,
        metric: dict[str, Any],
        source_targets: list[dict[str, Any]],
        selection_source: str,
    ) -> dict[str, Any]:
        project_root = project_roots[(language, project)]
        entry = {
            "project_root": project_root,
            "language": OUTPUT_LANGUAGES[language],
            "target_type": "source_file",
            "src_file": src_file,
            "test_file": TEST_PATH_GENERATORS[language](
                project_root,
                str(Path(project_root) / src_file),
            ),
            "nloc": metric["nloc"],
            "concrete_method_count": metric["concrete_method_count"],
            "callable_entry_count": metric.get("callable_entry_count", 0),
            "total_cyclomatic_complexity": metric["total_cyclomatic_complexity"],
            "cross_file_internal_method_fanout": metric.get(
                "cross_file_internal_method_fanout", 0
            ),
            "resolved_cross_file_internal_method_fanout": metric.get(
                "resolved_cross_file_internal_method_fanout", 0
            ),
            "average_function_cyclomatic_complexity": (
                metric["total_cyclomatic_complexity"] / metric["concrete_method_count"]
            ),
            "loc_ge_100_target_count": len(source_targets),
            "loc_ge_100_targets": [
                compact_function_target(record)
                for record in sorted(
                    source_targets,
                    key=lambda record: (record.get("start_line", 0), record.get("name", "")),
                )
            ],
            "selection_source": selection_source,
        }
        return entry

    for key in sorted(function_targets):
        language, project, src_file = key
        metric = metrics[key]
        if src_file in excluded_paths:
            continue
        if metric["nloc"] < min_nloc or metric["concrete_method_count"] < min_functions:
            continue
        if metric["total_cyclomatic_complexity"] < min_total_cyclomatic_complexity:
            continue
        if (
            metric.get("cross_file_internal_method_fanout", 0)
            < min_cross_file_internal_method_fanout
        ):
            continue
        if (
            metric.get("resolved_cross_file_internal_method_fanout", 0)
            < min_resolved_cross_file_internal_method_fanout
        ):
            continue
        if (
            metric["total_cyclomatic_complexity"] / metric["concrete_method_count"]
            < min_average_cyclomatic_complexity
        ):
            continue

        source_targets = function_targets[key]
        entries[(language, project)].append(
            make_entry(
                language,
                project,
                src_file,
                metric,
                source_targets,
                "target_function_file",
            )
        )

    if fallback_empty_projects:
        for language, project in sorted(project_roots):
            if entries.get((language, project)):
                continue
            for key, metric in sorted(metrics.items()):
                metric_language, metric_project, src_file = key
                if (metric_language, metric_project) != (language, project):
                    continue
                if src_file in excluded_paths:
                    continue
                if metric["nloc"] < min_nloc or metric["concrete_method_count"] < min_functions:
                    continue
                if metric["total_cyclomatic_complexity"] < min_total_cyclomatic_complexity:
                    continue
                if (
                    metric.get("cross_file_internal_method_fanout", 0)
                    < min_cross_file_internal_method_fanout
                ):
                    continue
                if (
                    metric.get("resolved_cross_file_internal_method_fanout", 0)
                    < min_resolved_cross_file_internal_method_fanout
                ):
                    continue
                if (
                    metric["total_cyclomatic_complexity"] / metric["concrete_method_count"]
                    < min_average_cyclomatic_complexity
                ):
                    continue
                entries[(language, project)].append(
                    make_entry(
                        language,
                        project,
                        src_file,
                        metric,
                        [],
                        "project_fallback",
                    )
                )
    return entries


def write_entries(
    output_root: Path,
    entries: dict[tuple[str, str], list[dict[str, Any]]],
    projects: set[tuple[str, str]],
) -> None:
    if output_root.exists():
        raise FileExistsError(f"Refusing to overwrite existing output directory: {output_root}")
    for language, project in sorted(projects):
        records = entries.get((language, project), [])
        output_path = output_root / language / f"{project}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def filter_by_callable_entries(
    entries: dict[tuple[str, str], list[dict[str, Any]]],
    min_callable_entries: int,
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    filtered: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for (language, project), records in sorted(entries.items()):
        kept = []
        for record in records:
            if record["callable_entry_count"] >= min_callable_entries:
                kept.append(record)
        if kept:
            filtered[(language, project)] = kept
    return filtered


def main() -> int:
    args = parse_args()
    function_targets, projects = load_function_targets(args.loc_dataset)
    metrics, project_roots = load_file_metrics(
        args.file_metrics,
        set(function_targets),
        projects,
        include_all_project_files=args.fallback_empty_projects,
    )
    entries = build_entries(
        function_targets,
        metrics,
        project_roots,
        min_nloc=args.min_nloc,
        min_functions=args.min_functions,
        min_total_cyclomatic_complexity=args.min_total_cyclomatic_complexity,
        min_cross_file_internal_method_fanout=args.min_cross_file_internal_method_fanout,
        min_resolved_cross_file_internal_method_fanout=(
            args.min_resolved_cross_file_internal_method_fanout
        ),
        min_average_cyclomatic_complexity=args.min_average_cyclomatic_complexity,
        excluded_paths=set(args.exclude),
        fallback_empty_projects=False,
    )
    entries = filter_by_callable_entries(entries, args.min_callable_entries)
    if args.fallback_empty_projects:
        fallback_entries = build_entries(
            {},
            metrics,
            project_roots,
            min_nloc=args.min_nloc,
            min_functions=args.min_functions,
            min_total_cyclomatic_complexity=args.min_total_cyclomatic_complexity,
            min_cross_file_internal_method_fanout=(
                args.min_cross_file_internal_method_fanout
            ),
            min_resolved_cross_file_internal_method_fanout=(
                args.min_resolved_cross_file_internal_method_fanout
            ),
            min_average_cyclomatic_complexity=args.min_average_cyclomatic_complexity,
            excluded_paths=set(args.exclude),
            fallback_empty_projects=True,
        )
        fallback_entries = filter_by_callable_entries(
            fallback_entries,
            args.min_callable_entries,
        )
        for project, records in fallback_entries.items():
            primary_records = entries.get(project, [])
            if len(primary_records) >= args.fallback_min_primary_files:
                continue
            existing_paths = {record["src_file"] for record in primary_records}
            entries.setdefault(project, []).extend(
                record for record in records if record["src_file"] not in existing_paths
            )
    write_entries(args.output, entries, projects)
    file_count = sum(len(records) for records in entries.values())
    function_count = sum(
        record["loc_ge_100_target_count"]
        for records in entries.values()
        for record in records
    )
    print(
        f"Wrote {file_count} file targets covering {function_count} loc_ge_100 functions "
        f"across {len(entries)} runnable project datasets to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
