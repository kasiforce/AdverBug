#!/usr/bin/env python3

"""Build one aggregate JSON report from per-project Java evaluation results."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _rate(passed: int, total: int) -> float:
    return passed / total if total else 0.0


def _metric(passed: int, total: int) -> dict[str, int | float]:
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": _rate(passed, total),
    }


def _coverage(covered: int, total: int) -> dict[str, int | float]:
    return {
        "total": total,
        "covered": covered,
        "missed": total - covered,
        "rate": _rate(covered, total),
    }


def _empty_totals() -> dict[str, int]:
    return {
        "targets": 0,
        "syntax_passed": 0,
        "compile_passed": 0,
        "execution_passed": 0,
        "test_passed": 0,
        "function_reports": 0,
        "function_line_total": 0,
        "function_line_covered": 0,
        "function_branch_total": 0,
        "function_branch_covered": 0,
        "files": 0,
        "file_reports": 0,
        "file_line_total": 0,
        "file_line_covered": 0,
        "file_branch_total": 0,
        "file_branch_covered": 0,
    }


def _add_totals(destination: dict[str, int], source: dict[str, int]) -> None:
    for key in destination:
        destination[key] += source[key]


def _execution_passed(evaluation: dict[str, Any]) -> bool:
    """Compilation succeeded and tests ran without JUnit runtime errors.

    JUnit assertion failures are represented by ``failures`` and are
    intentionally allowed here. They still make ``test_pass`` false.
    """

    summary = evaluation.get("test_summary") or {}
    return bool(
        evaluation.get("compile_pass") is True
        and summary.get("report_count", 0) > 0
        and summary.get("errors", 0) == 0
        and not summary.get("parse_errors")
    )


def collect_project(project_dir: Path, coverage_set: str) -> tuple[dict[str, Any], dict[str, int]]:
    evaluated_path = project_dir / "evaluated_results.json"
    file_coverage_path = project_dir / "file_coverage.json"
    items = json.loads(evaluated_path.read_text(encoding="utf-8"))
    file_coverage_sets = json.loads(file_coverage_path.read_text(encoding="utf-8"))
    files = file_coverage_sets.get(coverage_set, {})
    if not isinstance(items, list) or not isinstance(files, dict):
        raise ValueError(f"Invalid evaluation data in {project_dir}")

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


def render_metrics(totals: dict[str, int]) -> dict[str, Any]:
    targets = totals["targets"]
    return {
        "target_count": targets,
        "syntax": _metric(totals["syntax_passed"], targets),
        "compilation": _metric(totals["compile_passed"], targets),
        "execution": _metric(totals["execution_passed"], targets),
        "tests": _metric(totals["test_passed"], targets),
        "function_coverage": {
            "targets_total": targets,
            "targets_with_report": totals["function_reports"],
            "line": _coverage(totals["function_line_covered"], totals["function_line_total"]),
            "branch": _coverage(
                totals["function_branch_covered"], totals["function_branch_total"]
            ),
        },
        "file_coverage": {
            "files_total": totals["files"],
            "files_with_report": totals["file_reports"],
            "line": _coverage(totals["file_line_covered"], totals["file_line_total"]),
            "branch": _coverage(totals["file_branch_covered"], totals["file_branch_total"]),
        },
    }


def atomic_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, default=Path("eval_results/java"))
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--coverage-set",
        choices=("passing", "all_executed"),
        default="passing",
        help="Merged JaCoCo set used for file-level coverage",
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
        parser.error(f"No Java project evaluation results found under {root}")

    aggregate = _empty_totals()
    projects: dict[str, Any] = {}
    for project_dir in project_dirs:
        metrics, totals = collect_project(project_dir, args.coverage_set)
        projects[project_dir.name] = metrics
        _add_totals(aggregate, totals)

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "language": "Java",
        "coverage_set": args.coverage_set,
        "definitions": {
            "execution_pass": (
                "The generated test suite compiled and produced a parseable JUnit report with "
                "zero runtime errors. Assertion failures are allowed."
            ),
            "test_pass": "The generated test suite completed with zero failures and zero errors.",
            "coverage_rate": "Micro-average: sum(covered) / sum(total).",
            "function_coverage": "Coverage of each benchmark target method in its isolated run.",
            "file_coverage": (
                f"Coverage of unique target production files after merging the {args.coverage_set} "
                "JaCoCo execution data within each project."
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
