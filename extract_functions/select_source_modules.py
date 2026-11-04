#!/usr/bin/env python3
"""Aggregate file-level selections into non-colliding source modules.

This report deliberately does not introduce another hard threshold: a module is
reported when it contains at least one file selected by
``select_source_test_files.py``. Module-level metrics are sums over those
selected files, making the report useful for choosing a later module budget.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def _module_key(src_file: str, language: str) -> str:
    parts = Path(src_file).parts
    if not parts:
        return "."
    depth = 2 if language == "javascript" else 1
    return "/".join(parts[:depth])


def aggregate_modules(data: dict[str, Any]) -> dict[str, Any]:
    language = data["language"]
    groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "module": "",
            "selected_file_count": 0,
            "nloc": 0,
            "concrete_method_count": 0,
            "callable_entry_count": 0,
            "total_cyclomatic_complexity": 0,
            "cross_file_internal_method_fanout": 0,
            "files": [],
        }
    )
    for record in data.get("selected_files", []):
        module = _module_key(record["src_file"], language)
        group = groups[module]
        group["module"] = module
        group["selected_file_count"] += 1
        for key in (
            "nloc",
            "concrete_method_count",
            "callable_entry_count",
            "total_cyclomatic_complexity",
            "cross_file_internal_method_fanout",
        ):
            group[key] += record.get(key, 0)
        group["files"].append(record["src_file"])

    modules = sorted(
        groups.values(),
        key=lambda group: (
            -group["total_cyclomatic_complexity"],
            -group["cross_file_internal_method_fanout"],
            group["module"],
        ),
    )
    return {
        "schema_version": 1,
        "language": language,
        "project_root": data["project_root"],
        "file_selection_thresholds": data["thresholds"],
        "module_grouping": (
            "first_path_component"
            if language != "javascript"
            else "first_two_path_components"
        ),
        "production_file_count": data["production_file_count"],
        "file_selected_count": data["selected_file_count"],
        "module_count": len(modules),
        "modules": modules,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    result = aggregate_modules(data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Selected files: {result['file_selected_count']}; modules: {result['module_count']}; wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
