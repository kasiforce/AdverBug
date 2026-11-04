#!/usr/bin/env python3
"""Filter results/java_missing to loc_ge_100_out_3_loose Java functions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from filter_root_java_results import atomic_json_dump, filter_run_dir, identity


RESULT_SPECS = (
    ("leaf_deepseek_testgen_missing.json", "leaf", "leaf"),
    ("leaf_limit_retry.json", "leaf", "leaf_limit_retry"),
    ("ofdrw_deepseek_testgen_missing.json", "ofdrw", "ofdrw"),
    ("parquet_deepseek_testgen_missing.json", "parquet", "parquet"),
    ("undertow_deepseek_testgen_missing.json", "undertow", "undertow"),
    ("undertow_limit_retry.json", "undertow", "undertow_limit_retry"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    datasets: dict[str, list[dict]] = {}
    summary: list[dict] = []
    for result_name, dataset_name, run_name in RESULT_SPECS:
        result_path = args.results_dir / result_name
        if not result_path.is_file():
            continue
        if dataset_name not in datasets:
            datasets[dataset_name] = json.loads(
                (args.dataset_dir / f"{dataset_name}.json").read_text(encoding="utf-8")
            )
        dataset = datasets[dataset_name]
        allowed = {identity(item) for item in dataset}
        allowed_tokens = {
            f"__{item.get('name', '')}__{item.get('start_line', '')}__"
            for item in dataset
        }
        results = json.loads(result_path.read_text(encoding="utf-8"))
        kept = [item for item in results if identity(item) in allowed]
        trajectories_removed, status_lines_removed, instance_dirs_removed = (
            filter_run_dir(
                args.results_dir / run_name, allowed_tokens, apply=args.apply
            )
        )
        if args.apply and len(kept) != len(results):
            atomic_json_dump(result_path, kept)
        summary.append({
            "file": result_name,
            "dataset": dataset_name,
            "before": len(results),
            "after": len(kept),
            "removed": len(results) - len(kept),
            "trajectories_removed": trajectories_removed,
            "status_lines_removed": status_lines_removed,
            "instance_dirs_removed": instance_dirs_removed,
        })

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
