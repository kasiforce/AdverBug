#!/usr/bin/env python3
"""Summarize Java dynamic-call evaluator outputs without double counting methods."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def method_key(entry: dict[str, Any]) -> tuple[str, str, str]:
    return (str(entry.get("callee_class", "")), str(entry.get("callee_method", "")), str(entry.get("descriptor", "")))


def summarize(path: Path) -> dict[str, Any]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    static: dict[tuple[str, str, str], dict[str, Any]] = {}
    dynamic: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        for entry in row.get("static_called_functions", []):
            static[method_key(entry)] = entry
        for entry in row.get("direct_called_functions", []):
            dynamic[method_key(entry)] = entry
    candidates = set(static) | set(dynamic)
    coverage: dict[tuple[str, str, str], dict[str, Any]] = {}
    for key in candidates:
        coverage[key] = dynamic.get(key) or static.get(key) or {}
    result: dict[str, Any] = {
        "target_count": len(rows),
        "compile_pass_count": sum(row.get("compile_pass") is True for row in rows),
        "test_pass_count": sum(row.get("test_pass") is True for row in rows),
        "static_called_function_count": len(static),
        "executed_called_function_count": len(dynamic),
        "candidate_called_function_count": len(candidates),
        "execution_rate": len(dynamic) / len(candidates) if candidates else None,
    }
    for kind in ("line", "branch"):
        covered = total = matched = 0
        for entry in coverage.values():
            counter = (entry.get("coverage") or {}).get(kind)
            if not counter:
                continue
            matched += 1
            covered += int(counter.get("covered", 0) or 0)
            total += int(counter.get("total", 0) or 0)
        result[kind] = {
            "covered": covered,
            "total": total,
            "rate": covered / total if total else None,
            "matched_function_count": matched,
            "unmatched_function_count": len(candidates) - matched,
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = {}
    canonical = {
        "dynamic_leaf": "leaf",
        "dynamic_undertow_asm9_full": "undertow",
        "dynamic_flink": "flink",
        "dynamic_twelvemonkeys_compat": "twelvemonkeys",
    }
    for path in sorted(args.results_dir.glob("dynamic_*/dynamic_call_results.json")):
        project = canonical.get(path.parent.name)
        if project:
            report[project] = summarize(path)
    totals = {"projects_with_results": len(report), "targets": sum(v["target_count"] for v in report.values())}
    print(json.dumps({"projects": report, "totals": totals}, ensure_ascii=False, indent=2))
    if args.output:
        args.output.write_text(json.dumps({"projects": report, "totals": totals}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
