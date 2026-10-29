#!/usr/bin/env python3

"""Summarize mini-swe-agent time and cost for LOC>=100 Java targets."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from summarize_java import atomic_dump
from summarize_java_loc_ge_100 import PROJECTS, _select_items
from summarize_miniswe_javascript import _metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=Path("dataset/loc_ge_100/java"))
    parser.add_argument("--results-root", type=Path, default=Path("eval_results/java"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    dataset_root = args.dataset_root.resolve()
    results_root = args.results_root.resolve()
    output = (args.output or results_root / "loc_ge_100" / "mini_swe_summary.json").resolve()

    totals: list[int | float] = [0, 0, 0, 0.0, 0.0]
    projects: dict[str, Any] = {}
    for project, (dataset_name, result_name) in PROJECTS.items():
        items, dataset_target_count = _select_items(
            dataset_root / dataset_name,
            results_root / result_name / "evaluated_results.json",
        )
        agents = [item.get("mini_swe_agent") or {} for item in items]
        times = [float(agent["time_seconds"]) for agent in agents if agent.get("time_seconds") is not None]
        costs = [float(agent["model_cost"]) for agent in agents if agent.get("model_cost") is not None]
        raw = (len(items), len(times), len(costs), sum(times), sum(costs))
        project_metrics = _metrics(*raw)
        project_metrics["dataset_target_count"] = dataset_target_count
        project_metrics["skipped_not_successfully_generated"] = dataset_target_count - len(items)
        projects[project] = project_metrics
        for index, value in enumerate(raw):
            totals[index] += value

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "language": "Java",
        "dataset": str(dataset_root),
        "selection": "LOC>=100 targets with mini-swe-agent exit_status=Submitted.",
        "overall": _metrics(*totals),
        "projects": projects,
    }
    atomic_dump(output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
