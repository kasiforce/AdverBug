#!/usr/bin/env python3
"""Filter root-level Java function results to loc_ge_100_out_3_loose."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any


IDENTITY_FIELDS = (
    "src_file",
    "name",
    "start_line",
    "end_line",
    "full_class_name",
    "method_key",
)

RESULT_SPECS = (
    ("leaf_deepseek_testgen.json", "leaf", ("leaf_deepseek_run",)),
    ("leaf_renderFragmentInternal_retry_testgen.json", "leaf", ("leaf_renderFragmentInternal_retry",)),
    ("ofdrw_deepseek_testgen.json", "ofdrw", ("ofdrw_deepseek_run",)),
    ("parquet_deepseek_testgen.json", "parquet", ("parquet_deepseek_run",)),
    ("parquet_deepseek_testgen_retry.json", "parquet", ("parquet_deepseek_run_retry",)),
    ("twelvemonkeys_deepseek_testgen.json", "TwelveMonkeys", ("twelvemonkeys_deepseek_run",)),
    ("undertow_deepseek_testgen.json", "undertow", ("undertow_deepseek_run",)),
)


def identity(item: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(item.get(field, "")) for field in IDENTITY_FIELDS)


def atomic_json_dump(path: Path, value: Any) -> None:
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def instance_allowed(instance_id: str, allowed_tokens: set[str]) -> bool:
    return any(token in instance_id for token in allowed_tokens)


def filter_run_dir(
    run_dir: Path, allowed_tokens: set[str], *, apply: bool
) -> tuple[int, int, int]:
    trajectories_removed = 0
    status_lines_removed = 0
    instance_dirs_removed = 0
    for path in run_dir.rglob("trajectories.json") if run_dir.is_dir() else ():
        trajectories = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(trajectories, dict):
            continue
        filtered = {
            key: value for key, value in trajectories.items()
            if instance_allowed(str(key), allowed_tokens)
        }
        trajectories_removed += len(trajectories) - len(filtered)
        if apply and len(filtered) != len(trajectories):
            atomic_json_dump(path, filtered)

    for path in run_dir.rglob("exit_statuses_*.yaml") if run_dir.is_dir() else ():
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        filtered_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- ") and not instance_allowed(
                stripped[2:], allowed_tokens
            ):
                status_lines_removed += 1
                continue
            filtered_lines.append(line)
        if apply and len(filtered_lines) != len(lines):
            path.write_text("".join(filtered_lines), encoding="utf-8")
    if run_dir.is_dir():
        for child in run_dir.iterdir():
            if (child.is_dir() and list(child.glob("*.traj.json"))
                    and not instance_allowed(child.name, allowed_tokens)):
                instance_dirs_removed += 1
                if apply:
                    shutil.rmtree(child)
    return trajectories_removed, status_lines_removed, instance_dirs_removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    dataset_cache: dict[str, list[dict[str, Any]]] = {}
    run_specs: dict[str, tuple[str, set[str]]] = {}
    summary: list[dict[str, Any]] = []
    for result_name, dataset_name, run_names in RESULT_SPECS:
        result_path = args.results_dir / result_name
        if not result_path.is_file():
            continue
        if dataset_name not in dataset_cache:
            dataset_cache[dataset_name] = json.loads(
                (args.dataset_dir / f"{dataset_name}.json").read_text(encoding="utf-8")
            )
        dataset = dataset_cache[dataset_name]
        allowed = {identity(item) for item in dataset}
        allowed_tokens = {
            f"__{item.get('name', '')}__{item.get('start_line', '')}__"
            for item in dataset
        }
        results = json.loads(result_path.read_text(encoding="utf-8"))
        kept = [item for item in results if identity(item) in allowed]
        if args.apply and len(kept) != len(results):
            atomic_json_dump(result_path, kept)
        summary.append({
            "file": result_name,
            "dataset": dataset_name,
            "before": len(results),
            "after": len(kept),
            "removed": len(results) - len(kept),
        })
        for run_name in run_names:
            run_specs[run_name] = (dataset_name, allowed_tokens)

    for run_name, (dataset_name, allowed_tokens) in sorted(run_specs.items()):
        trajectories_removed, status_lines_removed, instance_dirs_removed = filter_run_dir(
            args.results_dir / run_name, allowed_tokens, apply=args.apply
        )
        summary.append({
            "run_dir": run_name,
            "dataset": dataset_name,
            "trajectories_removed": trajectories_removed,
            "status_lines_removed": status_lines_removed,
            "instance_dirs_removed": instance_dirs_removed,
        })

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
