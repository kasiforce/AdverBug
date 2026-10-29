#!/usr/bin/env python3

"""Summarize mini-swe-agent generation time and model cost for JavaScript."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from summarize_java import atomic_dump


def _metrics(function_count: int, time_count: int, cost_count: int, time: float, cost: float) -> dict[str, Any]:
    return {
        "function_count": function_count,
        "functions_with_time": time_count,
        "functions_with_cost": cost_count,
        "total_time_seconds": time,
        "average_time_seconds_per_function": time / time_count if time_count else 0.0,
        "total_model_cost": cost,
        "average_model_cost_per_function": cost / cost_count if cost_count else 0.0,
    }


def collect_project(path: Path) -> tuple[dict[str, Any], tuple[int, int, int, float, float]]:
    items = json.loads((path / "evaluated_results.json").read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise ValueError(f"Invalid evaluation data in {path}")

    agents = [item.get("mini_swe_agent") or {} for item in items]
    times = [float(agent["time_seconds"]) for agent in agents if agent.get("time_seconds") is not None]
    costs = [float(agent["model_cost"]) for agent in agents if agent.get("model_cost") is not None]
    raw = (len(items), len(times), len(costs), sum(times), sum(costs))
    return _metrics(*raw), raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, default=Path("eval_results/js"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = args.results_root.resolve()
    output = (args.output or root / "mini_swe_summary.json").resolve()
    project_dirs = sorted(
        path for path in root.iterdir()
        if path.is_dir() and (path / "evaluated_results.json").is_file()
    )
    if not project_dirs:
        parser.error(f"No JavaScript evaluation results found under {root}")

    totals = [0, 0, 0, 0.0, 0.0]
    projects: dict[str, Any] = {}
    for project_dir in project_dirs:
        projects[project_dir.name], raw = collect_project(project_dir)
        for index, value in enumerate(raw):
            totals[index] += value

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "language": "JavaScript",
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
