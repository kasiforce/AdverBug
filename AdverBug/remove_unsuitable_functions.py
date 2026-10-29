#!/usr/bin/env python3
"""Remove reviewed `exclude` rows from a materialized benchmark dataset.

The source candidate JSON files are not touched.  Removed records, their
original indices, and audit reasons are saved so the operation is auditable
and reversible.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path


IDENTITY_FIELDS = ("src_file", "start_line", "class_name", "function_name")


def atomic_json_write(path: Path, value: object) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset-dir", type=Path,
        default=Path("dataset/benchmark_balanced_200_call_degree"),
    )
    parser.add_argument(
        "--audit", type=Path,
        default=Path(
            "dataset/benchmark_balanced_200_call_degree/suitability/"
            "recommended_exclusions.csv"
        ),
    )
    parser.add_argument(
        "--removed-output", type=Path,
        default=Path(
            "dataset/benchmark_balanced_200_call_degree/suitability/"
            "removed_functions.json"
        ),
    )
    args = parser.parse_args()

    with args.audit.open(newline="", encoding="utf-8-sig") as handle:
        exclusions = list(csv.DictReader(handle))
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in exclusions:
        grouped[(row["language"], row["project"])].append(row)

    # Preserve earlier removals when the benchmark is audited incrementally.
    # This keeps the recovery log complete after adding another project.
    existing_log = []
    if args.removed_output.exists():
        existing_payload = json.loads(
            args.removed_output.read_text(encoding="utf-8")
        )
        existing_log = existing_payload.get("removed_functions", [])
    removal_log = list(existing_log)
    existing_identities = {
        (
            row.get("language"), row.get("project"),
            row.get("record", {}).get("src_file"),
            row.get("record", {}).get("start_line"),
            row.get("record", {}).get("class_name") or "",
            row.get("record", {}).get("name"),
        )
        for row in existing_log
    }
    changed_files = []
    for (language, project), rows in sorted(grouped.items()):
        dataset_path = args.dataset_dir / language / f"{project}.json"
        records = json.loads(dataset_path.read_text(encoding="utf-8"))
        removals: dict[int, dict] = {}
        for row in rows:
            index = int(row["json_index"])
            if index < 0 or index >= len(records):
                raise IndexError(f"Invalid index {index} for {dataset_path}")
            record = records[index]
            expected = {
                "src_file": row["src_file"],
                "start_line": int(row["start_line"]),
                "class_name": row["class_name"],
                "function_name": row["function_name"],
            }
            actual = {
                "src_file": record.get("src_file", ""),
                "start_line": record.get("start_line"),
                "class_name": record.get("class_name") or "",
                "function_name": record.get("name", ""),
            }
            if actual != expected:
                raise ValueError(
                    f"Audit identity mismatch for {dataset_path}[{index}]: "
                    f"expected {expected}, found {actual}"
                )
            removals[index] = row

        kept = []
        for index, record in enumerate(records):
            if index not in removals:
                kept.append(record)
                continue
            audit = removals[index]
            identity = (
                language, project, record.get("src_file"),
                record.get("start_line"), record.get("class_name") or "",
                record.get("name"),
            )
            if identity in existing_identities:
                continue
            removal_log.append({
                "language": language,
                "project": project,
                "benchmark_json": str(dataset_path),
                "original_index": index,
                "category": audit["category"],
                "reason": audit["reason"],
                "record": record,
            })
            existing_identities.add(identity)
        atomic_json_write(dataset_path, kept)
        changed_files.append({
            "path": str(dataset_path),
            "before": len(records),
            "removed": len(removals),
            "after": len(kept),
        })

    args.removed_output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(args.removed_output, {
        "removed_count": len(removal_log),
        "newly_removed_count": len(removal_log) - len(existing_log),
        "changed_files": changed_files,
        "removed_functions": removal_log,
    })
    print(json.dumps({
        "removed_count": len(removal_log),
        "changed_files": changed_files,
        "removed_output": str(args.removed_output),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
