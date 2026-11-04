#!/usr/bin/env python3
"""Keep generated results that correspond to a selected function dataset."""

from __future__ import annotations

import argparse
import json
import os
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
RESULT_SUFFIX = "_deepseek_v4_1_flash_1017.json"


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


def filter_status_file(path: Path, removed_ids: set[str], *, apply: bool) -> int:
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    filtered = [
        line for line in lines
        if not any(line.strip() == f"- {instance_id}" for instance_id in removed_ids)
    ]
    removed = len(lines) - len(filtered)
    if apply and removed:
        path.write_text("".join(filtered), encoding="utf-8")
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    summary: list[dict[str, Any]] = []
    for language_dir in sorted(path for path in args.results_dir.iterdir() if path.is_dir()):
        language = language_dir.name
        for result_path in sorted(language_dir.glob(f"*{RESULT_SUFFIX}")):
            repository = result_path.name.removesuffix(RESULT_SUFFIX)
            dataset_path = args.dataset_dir / language / f"{repository}.json"
            if not dataset_path.is_file():
                summary.append({
                    "language": language,
                    "repository": repository,
                    "status": "dataset_missing",
                })
                continue

            dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
            results = json.loads(result_path.read_text(encoding="utf-8"))
            allowed = {identity(item) for item in dataset}
            kept = [item for item in results if identity(item) in allowed]
            removed_items = [item for item in results if identity(item) not in allowed]
            kept_ids = {
                str((item.get("mini_swe_agent") or {}).get("instance_id") or "")
                for item in kept
            } - {""}
            removed_ids = {
                str((item.get("mini_swe_agent") or {}).get("instance_id") or "")
                for item in removed_items
            } - {""}

            run_dir = language_dir / f"{repository}_run"
            trajectory_path = run_dir / "trajectories.json"
            trajectories_removed = 0
            if trajectory_path.is_file():
                trajectories = json.loads(trajectory_path.read_text(encoding="utf-8"))
                filtered_trajectories = {
                    key: value for key, value in trajectories.items() if key in kept_ids
                }
                trajectories_removed = len(trajectories) - len(filtered_trajectories)
                if args.apply and trajectories_removed:
                    atomic_json_dump(trajectory_path, filtered_trajectories)

            status_lines_removed = sum(
                filter_status_file(path, removed_ids, apply=args.apply)
                for path in sorted(run_dir.glob("exit_statuses_*.yaml"))
            )
            if args.apply and removed_items:
                atomic_json_dump(result_path, kept)

            summary.append({
                "language": language,
                "repository": repository,
                "before": len(results),
                "after": len(kept),
                "removed": len(removed_items),
                "removed_instance_ids": sorted(removed_ids),
                "trajectories_removed": trajectories_removed,
                "status_lines_removed": status_lines_removed,
                "status": "applied" if args.apply else "dry_run",
            })

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
