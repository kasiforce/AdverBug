#!/usr/bin/env python3

"""Build one aggregate JSON report from per-project JavaScript evaluation results."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from summarize_java import (
    _add_totals,
    _empty_totals,
    _execution_passed,
    atomic_dump,
    render_metrics,
)


def collect_project(project_dir: Path, coverage_set: str) -> tuple[dict[str, Any], dict[str, int]]:
    items = json.loads((project_dir / "evaluated_results.json").read_text(encoding="utf-8"))
    coverage_sets = json.loads((project_dir / "file_coverage.json").read_text(encoding="utf-8"))
    files = coverage_sets.get(coverage_set, {})
    if not isinstance(items, list) or not isinstance(files, dict):
        raise ValueError(f"Invalid evaluation data in {project_dir}")

    totals = _empty_totals()
    totals["targets"] = len(items)
    for item in items:
        evaluation = item.get("evaluation") or {}
        syntax = evaluation.get("syntax") or item.get("syntax_evaluation") or {}
        if syntax.get("correct") is True:
            totals["syntax_passed"] += 1
        if evaluation.get("compile_pass") is True:
            totals["compile_passed"] += 1
        if _execution_passed(evaluation):
            totals["execution_passed"] += 1
        if evaluation.get("test_pass") is True:
            totals["test_passed"] += 1

        target = (evaluation.get("coverage") or {}).get("target_function") or {}
        line = target.get("line") or {}
        branch = target.get("branch") or {}
        if target.get("matched_methods"):
            totals["function_reports"] += 1
            totals["function_line_total"] += int(line.get("total", 0))
            totals["function_line_covered"] += int(line.get("covered", 0))
            totals["function_branch_total"] += int(branch.get("total", 0))
            totals["function_branch_covered"] += int(branch.get("covered", 0))

    totals["files"] = len(files)
    for entry in files.values():
        if entry.get("report_found") is not True:
            continue
        totals["file_reports"] += 1
        line = entry.get("line") or {}
        branch = entry.get("branch") or {}
        totals["file_line_total"] += int(line.get("total", 0))
        totals["file_line_covered"] += int(line.get("covered", 0))
        totals["file_branch_total"] += int(branch.get("total", 0))
        totals["file_branch_covered"] += int(branch.get("covered", 0))

    return render_metrics(totals), totals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, default=Path("eval_results/js"))
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--coverage-set",
        choices=("passing", "all_executed"),
        default="all_executed",
        help="Merged Istanbul coverage set used for file-level coverage",
    )
    args = parser.parse_args()

    root = args.results_root.resolve()
    output = (args.output or root / "final_summary.json").resolve()
    project_dirs = sorted(
        path
        for path in root.iterdir()
        if path.is_dir()
        and (path / "evaluated_results.json").is_file()
        and (path / "file_coverage.json").is_file()
    )
    if not project_dirs:
        parser.error(f"No JavaScript project evaluation results found under {root}")

    aggregate = _empty_totals()
    projects: dict[str, Any] = {}
    for project_dir in project_dirs:
        metrics, totals = collect_project(project_dir, args.coverage_set)
        projects[project_dir.name] = metrics
        _add_totals(aggregate, totals)

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "language": "JavaScript",
        "coverage_set": args.coverage_set,
        "definitions": {
            "execution_pass": (
                "The generated test suite compiled and produced a parseable Jest report with "
                "zero runtime errors. Assertion failures are allowed."
            ),
            "test_pass": "The generated test suite completed with zero failures and zero errors.",
            "coverage_rate": "Micro-average: sum(covered) / sum(total).",
            "function_coverage": "Coverage of each benchmark target function in its isolated run.",
            "file_coverage": (
                f"Coverage of unique target production files after merging the {args.coverage_set} "
                "Istanbul execution data within each project."
            ),
        },
        "overall": render_metrics(aggregate),
        "projects": projects,
    }
    atomic_dump(output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
