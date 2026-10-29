#!/usr/bin/env python3

"""Summarize mini-swe-agent generation time and model cost for Python."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from summarize_java import atomic_dump
from summarize_miniswe_javascript import _metrics, collect_project


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, default=Path("eval_results/python"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = args.results_root.resolve()
    output = (args.output or root / "mini_swe_summary.json").resolve()
    project_dirs = sorted(
        path for path in root.iterdir()
        if path.is_dir() and (path / "evaluated_results.json").is_file()
    )
    if not project_dirs:
        parser.error(f"No Python evaluation results found under {root}")

    totals: list[int | float] = [0, 0, 0, 0.0, 0.0]
    projects: dict[str, Any] = {}
    for project_dir in project_dirs:
        projects[project_dir.name], raw = collect_project(project_dir)
        for index, value in enumerate(raw):
            totals[index] += value

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "language": "Python",
        "definitions": {
            "time": "Wall-clock generation time recorded by mini-swe-agent.",
            "model_cost": "Model cost recorded by mini-swe-agent.",
            "overall_average": "Weighted average across all functions.",
        },
        "overall": _metrics(*totals),
        "projects": projects,
    }
    atomic_dump(output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
