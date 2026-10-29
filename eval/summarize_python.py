#!/usr/bin/env python3

"""Build one aggregate JSON report from per-project Python evaluation results."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from summarize_java import (
    _add_totals,
    _empty_totals,
    atomic_dump,
    collect_project,
    render_metrics,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, default=Path("eval_results/python"))
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--coverage-set",
        choices=("passing", "all_executed"),
        default="all_executed",
        help="Merged coverage.py set used for file-level coverage",
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
        parser.error(f"No Python project evaluation results found under {root}")

    aggregate = _empty_totals()
    projects: dict[str, Any] = {}
    for project_dir in project_dirs:
        metrics, totals = collect_project(project_dir, args.coverage_set)
        projects[project_dir.name] = metrics
        _add_totals(aggregate, totals)

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "language": "Python",
        "coverage_set": args.coverage_set,
        "definitions": {
            "execution_pass": (
                "The generated test suite compiled and produced a parseable pytest report with "
                "zero runtime errors. Assertion failures are allowed."
            ),
            "test_pass": "The generated test suite completed with zero failures and zero errors.",
            "coverage_rate": "Micro-average: sum(covered) / sum(total).",
            "function_coverage": (
                "Coverage of each benchmark target function in its isolated run."
            ),
            "file_coverage": (
                f"Coverage of unique target production files after merging the {args.coverage_set} "
                "coverage.py execution data within each project."
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
