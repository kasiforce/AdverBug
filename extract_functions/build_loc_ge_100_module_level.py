#!/usr/bin/env python3
"""Build runnable module targets related to the loc_ge_100 dataset.

Projects first retain eligible modules containing a loc_ge_100 function. If a
project has no such module, every size-eligible module in that project is used
as a fallback.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

from select_directory_modules import _test_module
from select_java_test_files import _file_method_metrics
from select_source_test_files import _callable_entries


LANGUAGES = ("java", "js", "python")
OUTPUT_LANGUAGES = {
    "java": "java",
    "js": "javascript",
    "python": "python",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loc-dataset", type=Path, default=Path("dataset/loc_ge_100"))
    parser.add_argument("--file-metrics", type=Path, default=Path("dataset/file_level"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dataset/loc_ge_100_module_level_files3_10_nloc500"),
    )
    parser.add_argument("--min-files", type=int, default=3)
    parser.add_argument("--max-files", type=int, default=10)
    parser.add_argument("--min-nloc", type=int, default=500)
    parser.add_argument("--min-callable-entries", type=int, default=1)
    parser.add_argument("--min-total-cyclomatic-complexity", type=int, default=0)
    parser.add_argument(
        "--recursive-files",
        action="store_true",
        help="Count every production file recursively below each candidate directory.",
    )
    parser.add_argument(
        "--deepest-non-overlapping",
        action="store_true",
        help="When recursive candidate scopes overlap, retain only the deepest scopes.",
    )
    return parser.parse_args()


def compact_function_target(record: dict[str, Any]) -> dict[str, Any]:
    fields = ("name", "method_key", "src_file", "start_line", "end_line", "loc", "complexity")
    return {field: record[field] for field in fields if record.get(field) is not None}


def is_within_module(src_file: str, module: str) -> bool:
    file_parts = PurePosixPath(src_file).parts
    module_parts = PurePosixPath(module).parts
    return file_parts[: len(module_parts)] == module_parts


def retain_deepest_non_overlapping(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    kept_files: list[set[str]] = []
    for record in sorted(
        records,
        key=lambda item: (-len(PurePosixPath(item["module"]).parts), item["module"]),
    ):
        files = set(record["files"])
        if any(files & existing for existing in kept_files):
            continue
        kept.append(record)
        kept_files.append(files)
    return sorted(kept, key=lambda item: item["module"])


def build_project_entries(
    language: str,
    project: str,
    function_dataset: Path,
    metrics_dataset: Path,
    min_files: int,
    max_files: int,
    min_nloc: int,
    recursive_files: bool = False,
    deepest_non_overlapping: bool = False,
    min_callable_entries: int = 1,
    min_total_cyclomatic_complexity: int = 0,
) -> list[dict[str, Any]]:
    function_targets = json.loads(function_dataset.read_text(encoding="utf-8"))
    metrics_payload = json.loads(metrics_dataset.read_text(encoding="utf-8"))

    project_roots = {record["project_root"] for record in function_targets}
    if len(project_roots) != 1:
        raise ValueError(f"Expected one project root for {function_dataset}: {sorted(project_roots)}")
    project_root = project_roots.pop()

    direct_files_by_module: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in metrics_payload["all_files"]:
        module = Path(record["src_file"]).parent.as_posix()
        direct_files_by_module[module].append(record)

    files_by_module: dict[str, list[dict[str, Any]]] = {}
    targets_by_module: dict[str, list[dict[str, Any]]] = {}
    if recursive_files:
        candidate_modules = set(direct_files_by_module)
        files_by_module = {module: [] for module in candidate_modules}
        targets_by_module = {module: [] for module in candidate_modules}

        def candidate_ancestors(src_file: str) -> list[str]:
            parent_parts = PurePosixPath(src_file).parent.parts
            return [
                PurePosixPath(*parent_parts[:depth]).as_posix()
                for depth in range(1, len(parent_parts) + 1)
                if PurePosixPath(*parent_parts[:depth]).as_posix() in candidate_modules
            ]

        for record in metrics_payload["all_files"]:
            for module in candidate_ancestors(record["src_file"]):
                files_by_module[module].append(record)
        for record in function_targets:
            for module in candidate_ancestors(record["src_file"]):
                targets_by_module[module].append(record)
    else:
        for module, direct_files in direct_files_by_module.items():
            files_by_module[module] = direct_files
            targets_by_module[module] = [
                record
                for record in function_targets
                if Path(record["src_file"]).parent.as_posix() == module
            ]

    size_eligible_files = {
        record["src_file"]
        for files in files_by_module.values()
        if min_files <= len(files) <= max_files
        and sum(record.get("nloc", 0) for record in files) >= min_nloc
        for record in files
    }
    source_paths = [str(Path(project_root) / src_file) for src_file in size_eligible_files]
    if language == "java":
        callable_entries_by_file = {
            src_file: values.get("callable_entry_count", 0)
            for src_file, values in _file_method_metrics(
                Path(project_root), source_paths
            ).items()
        }
    else:
        callable_entries_by_file = _callable_entries(
            Path(project_root), source_paths, OUTPUT_LANGUAGES[language]
        )

    eligible: list[dict[str, Any]] = []
    for module, files in sorted(files_by_module.items()):
        if module == "." or not min_files <= len(files) <= max_files:
            continue
        nloc = sum(record.get("nloc", 0) for record in files)
        if nloc < min_nloc:
            continue
        total_cyclomatic_complexity = sum(
            record.get("total_cyclomatic_complexity", 0) for record in files
        )
        if total_cyclomatic_complexity < min_total_cyclomatic_complexity:
            continue
        callable_entry_count = sum(
            callable_entries_by_file.get(record["src_file"], 0) for record in files
        )
        if callable_entry_count < min_callable_entries:
            continue
        eligible.append(
            {
                "project_root": project_root,
                "language": OUTPUT_LANGUAGES[language],
                "target_type": "module",
                "module": module,
                "test_module": _test_module(module, OUTPUT_LANGUAGES[language]),
                "module_scope": "recursive_directory" if recursive_files else "direct_files",
                "files": sorted(record["src_file"] for record in files),
                "file_count": len(files),
                "nloc": nloc,
                "callable_entry_count": callable_entry_count,
                "concrete_method_count": sum(
                    record.get("concrete_method_count", 0) for record in files
                ),
                "total_cyclomatic_complexity": total_cyclomatic_complexity,
                "loc_ge_100_target_count": len(targets_by_module.get(module, [])),
                "loc_ge_100_targets": [
                    compact_function_target(record)
                    for record in sorted(
                        targets_by_module.get(module, []),
                        key=lambda record: (record.get("src_file", ""), record.get("start_line", 0)),
                    )
                ],
            }
        )

    primary = [record for record in eligible if record["loc_ge_100_target_count"] > 0]
    selected = primary or eligible
    selection_source = "target_function_module" if primary else "project_fallback"
    for record in selected:
        record["selection_source"] = selection_source
    if deepest_non_overlapping:
        selected = retain_deepest_non_overlapping(selected)
        for record in selected:
            record["overlap_resolution"] = "deepest_non_overlapping"
    return selected


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite existing output directory: {args.output}")

    dataset_count = 0
    module_count = 0
    primary_count = 0
    fallback_count = 0
    projects_without_targets: list[str] = []

    for language in LANGUAGES:
        for function_dataset in sorted((args.loc_dataset / language).glob("*.json")):
            if function_dataset.stem.endswith("_specification"):
                continue
            project = function_dataset.stem
            records = build_project_entries(
                language,
                project,
                function_dataset,
                args.file_metrics / language / f"{project}.json",
                args.min_files,
                args.max_files,
                args.min_nloc,
                args.recursive_files,
                args.deepest_non_overlapping,
                args.min_callable_entries,
                args.min_total_cyclomatic_complexity,
            )
            if not records:
                projects_without_targets.append(f"{language}/{project}")
                continue
            output_path = args.output / language / f"{project}.json"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(records, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            dataset_count += 1
            module_count += len(records)
            primary_count += sum(
                record["selection_source"] == "target_function_module" for record in records
            )
            fallback_count += sum(
                record["selection_source"] == "project_fallback" for record in records
            )

    print(
        f"Wrote {module_count} module targets ({primary_count} primary, {fallback_count} fallback) "
        f"across {dataset_count} runnable project datasets to {args.output}"
    )
    if projects_without_targets:
        print("No eligible modules: " + ", ".join(projects_without_targets))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
