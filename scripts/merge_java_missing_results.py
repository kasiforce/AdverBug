#!/usr/bin/env python3
"""Merge results/java_missing JSON records into their root result files.

Records are deduplicated by the full Java method identity. Existing root records
take precedence so rerunning this script is safe and does not overwrite a chosen
retry result with an older attempt.
"""

from __future__ import annotations

import argparse
import json
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

MERGE_GROUPS = {
    "leaf_deepseek_testgen.json": (
        "leaf_deepseek_testgen_missing.json",
        "leaf_limit_retry.json",
    ),
    "ofdrw_deepseek_testgen.json": ("ofdrw_deepseek_testgen_missing.json",),
    "parquet_deepseek_testgen.json": ("parquet_deepseek_testgen_missing.json",),
    "undertow_deepseek_testgen.json": (
        "undertow_deepseek_testgen_missing.json",
        "undertow_limit_retry.json",
    ),
}


def identity(record: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(record.get(field) for field in IDENTITY_FIELDS)


def load_records(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise ValueError(f"Expected a JSON array of objects: {path}")
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path, default=Path("results"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    missing_dir = args.results_dir / "java_missing"
    report = []

    for target_name, source_names in MERGE_GROUPS.items():
        target_path = args.results_dir / target_name
        target = load_records(target_path)
        merged = list(target)
        by_identity = {identity(record): record for record in target}
        incoming_count = duplicate_count = conflict_count = added_count = 0

        for source_name in source_names:
            for record in load_records(missing_dir / source_name):
                incoming_count += 1
                key = identity(record)
                existing = by_identity.get(key)
                if existing is not None:
                    duplicate_count += 1
                    if existing != record:
                        conflict_count += 1
                    continue
                by_identity[key] = record
                merged.append(record)
                added_count += 1

        if args.apply and added_count:
            target_path.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        report.append(
            {
                "target": target_name,
                "before": len(target),
                "incoming": incoming_count,
                "duplicates": duplicate_count,
                "conflicts_kept_target": conflict_count,
                "added": added_count,
                "after": len(merged),
            }
        )

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
