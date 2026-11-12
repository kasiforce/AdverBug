#!/usr/bin/env python3
"""Summarize direct project-callee coverage from JavaScript Istanbul runs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

EVAL_DIR = Path(__file__).resolve().parent
ROOT = EVAL_DIR.parent
sys.path.insert(0, str(ROOT / "extract_functions"))

from extract_func import build_repository_index, resolve_project_callees  # noqa: E402
from eval_js import _find_file_entry, _target_function_metrics  # noqa: E402


def metric(covered: int, total: int) -> dict[str, int | float | None]:
    return {
        "covered": covered,
        "total": total,
        "rate": covered / total if total else None,
    }


def callee_record(callee: Any) -> dict[str, Any]:
    return {
        "src_file": callee.path,
        "name": callee.name,
        "class_name": callee.class_name,
        "start_line": callee.start_line,
        "end_line": callee.end_line,
        "target_type": "function",
    }


def coverage_for_callee(report: dict[str, Any], callee: Any) -> dict[str, Any] | None:
    record = callee_record(callee)
    file_key, entry = _find_file_entry(report, record)
    if entry is None:
        return None
    coverage = _target_function_metrics(entry, record)
    if coverage is not None:
        coverage["file_key"] = file_key
    return coverage


def resolved_callees(item: dict[str, Any], index: dict[str, Any]) -> list[Any]:
    """Resolve callees, including class-field arrow functions named anonymous by the index."""
    try:
        return resolve_project_callees(item, index)
    except ValueError:
        path = str(item.get("src_file") or "")
        start = int(item.get("start_line") or 0)
        end = int(item.get("end_line") or 0)
        matches = [
            function
            for function in index["functions"]
            if function.path == path
            and function.start_line == start
            and (not end or function.end_line == end)
        ]
        if len(matches) != 1:
            raise
        fallback = dict(item)
        fallback["name"] = matches[0].name
        fallback["class_name"] = matches[0].class_name
        return resolve_project_callees(fallback, index)


def summarize(data_file: Path, run_dir: Path) -> dict[str, Any]:
    items = json.loads(data_file.read_text(encoding="utf-8"))
    dynamic_path = run_dir / "dynamic_call_results.json"
    dynamic = json.loads(dynamic_path.read_text(encoding="utf-8"))
    if len(items) != len(dynamic):
        raise ValueError(f"Target/run count mismatch: {len(items)} != {len(dynamic)}")

    project_root = Path(str(items[0].get("project_root") or ".")).resolve()
    index = build_repository_index(project_root)
    targets: list[dict[str, Any]] = []
    total_candidates = total_measured = 0
    line_covered = line_total = branch_covered = branch_total = 0

    for item, run in zip(items, dynamic):
        callees = resolved_callees(item, index)
        instance_root = run_dir / "runs" / run["instance_id"]
        clean_coverage = instance_root / "clean" / "coverage" / "coverage-final.json"
        coverage_path = (
            clean_coverage
            if clean_coverage.is_file()
            else instance_root / "coverage" / "coverage-final.json"
        )
        try:
            report = json.loads(coverage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            report = {}
        callee_results: list[dict[str, Any]] = []
        for callee in callees:
            coverage = coverage_for_callee(report, callee)
            result = {
                "function": callee.qualified_name or callee.name,
                "name": callee.name,
                "src_file": callee.path,
                "start_line": callee.start_line,
                "end_line": callee.end_line,
                "coverage": coverage,
                "coverage_status": "measured" if coverage is not None else "not_in_istanbul_report",
            }
            callee_results.append(result)
            total_candidates += 1
            if coverage is None:
                continue
            total_measured += 1
            line = coverage["line"]
            branch = coverage["branch"]
            line_covered += int(line["covered"])
            line_total += int(line["total"])
            branch_covered += int(branch["covered"])
            branch_total += int(branch["total"])
        targets.append(
            {
                "target_function": item.get("name"),
                "src_file": item.get("src_file"),
                "resolved_direct_callee_count": len(callees),
                "measured_callee_count": sum(r["coverage"] is not None for r in callee_results),
                "callees": callee_results,
            }
        )

    return {
        "data_file": str(data_file),
        "project_root": str(project_root),
        "target_count": len(targets),
        "definitions": {
            "callee_scope": "Uniquely resolved direct same-project production callees.",
            "coverage": "Istanbul statement-line and branch coverage within each callee source range.",
            "aggregation": "Micro-average over measurable target-callee pairs; a callee used by two targets is counted once per isolated target run.",
        },
        "resolved_direct_callee_count": total_candidates,
        "measured_callee_count": total_measured,
        "unmeasured_callee_count": total_candidates - total_measured,
        "line": metric(line_covered, line_total),
        "branch": metric(branch_covered, branch_total),
        "targets": targets,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-file", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = summarize(args.data_file.resolve(), args.run_dir.resolve())
    output = (args.output or args.run_dir / "callee_coverage_summary.json").resolve()
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "target_count", "resolved_direct_callee_count", "measured_callee_count",
        "unmeasured_callee_count", "line", "branch",
    )}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
