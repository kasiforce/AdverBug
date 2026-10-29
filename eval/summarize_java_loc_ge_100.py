#!/usr/bin/env python3

"""Re-merge and summarize Java evaluations for LOC>=100 benchmark targets."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eval_java import (
    DEFAULT_JACOCO_VERSION,
    collect_merged_file_coverage,
    merge_coverage,
)
from summarize_java import (
    _add_totals,
    _empty_totals,
    _execution_passed,
    atomic_dump,
    render_metrics,
)


PROJECTS = {
    "flink": ("flink.json", "flink_deepseek_v4_1_flash_1017"),
    "leaf": ("leaf.json", "leaf"),
    "ofdrw": ("ofdrw.json", "ofdrw"),
    "parquet": ("parquet.json", "parquet"),
    "twelvemonkeys": ("TwelveMonkeys.json", "twelvemonkeys"),
    "undertow": ("undertow.json", "undertow"),
}


def _target_key(item: dict[str, Any]) -> tuple[str, str, int]:
    return (
        str(item.get("src_file", "")),
        str(item.get("name", "")),
        int(item.get("start_line", -1)),
    )


def _select_items(dataset_path: Path, evaluated_path: Path) -> tuple[list[dict[str, Any]], int]:
    targets = json.loads(dataset_path.read_text(encoding="utf-8"))
    evaluated = json.loads(evaluated_path.read_text(encoding="utf-8"))
    if not isinstance(targets, list) or not isinstance(evaluated, list):
        raise ValueError(f"Expected JSON lists in {dataset_path} and {evaluated_path}")

    wanted = {_target_key(item) for item in targets}
    selected = [
        item
        for item in evaluated
        if _target_key(item) in wanted
        and (item.get("mini_swe_agent") or {}).get("exit_status") == "Submitted"
    ]
    return selected, len(targets)


def _copy_exec_files(items: list[dict[str, Any]], source: Path, destination: Path) -> None:
    for item in items:
        relative = (item.get("evaluation") or {}).get("jacoco_exec")
        if not relative:
            continue
        source_path = source / str(relative)
        destination_path = destination / str(relative)
        if source_path.is_file():
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination_path)


def _collect_totals(items: list[dict[str, Any]], files: dict[str, Any]) -> dict[str, int]:
    totals = _empty_totals()
    totals["targets"] = len(items)
    for item in items:
        if (item.get("syntax_evaluation") or {}).get("correct") is True:
            totals["syntax_passed"] += 1
        evaluation = item.get("evaluation") or {}
        if evaluation.get("compile_pass") is True:
            totals["compile_passed"] += 1
        if _execution_passed(evaluation):
            totals["execution_passed"] += 1
        if evaluation.get("test_pass") is True:
            totals["test_passed"] += 1

        target = (evaluation.get("coverage") or {}).get("target_function") or {}
        if target.get("matched_methods"):
            line = target.get("line") or {}
            branch = target.get("branch") or {}
            totals["function_reports"] += 1
            totals["function_line_total"] += int(line.get("total", 0))
            totals["function_line_covered"] += int(line.get("covered", 0))
            totals["function_branch_total"] += int(branch.get("total", 0))
            totals["function_branch_covered"] += int(branch.get("covered", 0))

    totals["files"] = len(files)
    for entry in files.values():
        if entry.get("report_found") is not True:
            continue
        line = entry.get("line") or {}
        branch = entry.get("branch") or {}
        totals["file_reports"] += 1
        totals["file_line_total"] += int(line.get("total", 0))
        totals["file_line_covered"] += int(line.get("covered", 0))
        totals["file_branch_total"] += int(branch.get("total", 0))
        totals["file_branch_covered"] += int(branch.get("covered", 0))
    return totals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=Path("dataset/loc_ge_100/java"))
    parser.add_argument("--results-root", type=Path, default=Path("eval_results/java"))
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--merge-timeout", type=int, default=1800)
    parser.add_argument("--jacoco-version", default=DEFAULT_JACOCO_VERSION)
    parser.add_argument(
        "--reuse-merged",
        action="store_true",
        help="Reuse each subset's existing file_coverage.json instead of running JaCoCo merge",
    )
    args = parser.parse_args()

    dataset_root = args.dataset_root.resolve()
    results_root = args.results_root.resolve()
    output_dir = (args.output_dir or results_root / "loc_ge_100").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    aggregate = _empty_totals()
    projects: dict[str, Any] = {}
    for project, (dataset_name, result_name) in PROJECTS.items():
        source_dir = results_root / result_name
        project_output = output_dir / project
        project_output.mkdir(parents=True, exist_ok=True)
        generated_items, dataset_target_count = _select_items(
            dataset_root / dataset_name,
            source_dir / "evaluated_results.json",
        )
        items = [item for item in generated_items if item.get("evaluation")]
        _copy_exec_files(items, source_dir, project_output)
        source_summary = json.loads((source_dir / "summary.json").read_text(encoding="utf-8"))
        if args.reuse_merged:
            previous_summary = json.loads(
                (project_output / "summary.json").read_text(encoding="utf-8")
            )
            status = previous_summary.get("merge", {})
            files = json.loads(
                (project_output / "file_coverage.json").read_text(encoding="utf-8")
            ).get("all_executed", {})
        else:
            status = merge_coverage(
                image=str(source_summary["image"]),
                output_dir=project_output,
                results=items,
                kind="all_executed",
                jacoco_version=args.jacoco_version,
                timeout=args.merge_timeout,
            )
            files = collect_merged_file_coverage(
                project_output,
                items,
                "all_executed",
                status.get("modules", {}),
            )
        totals = _collect_totals(items, files)
        metrics = render_metrics(totals)
        metrics["dataset_target_count"] = dataset_target_count
        metrics["successfully_generated_count"] = len(generated_items)
        metrics["pending_evaluation_count"] = len(generated_items) - len(items)
        metrics["skipped_not_successfully_generated"] = dataset_target_count - len(generated_items)
        metrics["merge"] = status
        projects[project] = metrics
        _add_totals(aggregate, totals)

        atomic_dump(project_output / "evaluated_results.json", items)
        atomic_dump(project_output / "file_coverage.json", {"all_executed": files})
        atomic_dump(project_output / "summary.json", metrics)
        print(
            f"{project}: evaluated {len(items)}/{len(generated_items)} generated, "
            f"merge={status.get('success')}",
            flush=True,
        )

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "language": "Java",
        "dataset": str(dataset_root),
        "coverage_set": "all_executed",
        "definitions": {
            "selection": "Targets in the LOC>=100 dataset with mini-swe-agent exit_status=Submitted.",
            "execution_pass": (
                "The generated test suite compiled and produced a parseable JUnit report with "
                "zero runtime errors. Assertion failures are allowed."
            ),
            "test_pass": "The generated test suite completed with zero failures and zero errors.",
            "coverage_rate": "Micro-average: sum(covered) / sum(total).",
            "function_coverage": "Coverage of each selected target method in its isolated run.",
            "file_coverage": (
                "Coverage of unique target production files after re-merging only selected "
                "all-executed JaCoCo data within each project."
            ),
        },
        "overall": render_metrics(aggregate),
        "projects": projects,
    }
    atomic_dump(output_dir / "final_summary.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
