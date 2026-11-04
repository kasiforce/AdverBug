from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"
sys.path.insert(0, str(EVAL_DIR))

from eval_javascript_dynamic_calls import (  # noqa: E402
    _called_function_coverage,
    _dynamic_candidates,
)


def _coverage_entry() -> dict:
    return {
        "fnMap": {
            "0": {
                "name": "helper",
                "line": 10,
                "loc": {"start": {"line": 10}, "end": {"line": 14}},
            },
            "1": {
                "name": "other",
                "line": 20,
                "loc": {"start": {"line": 20}, "end": {"line": 22}},
            },
        },
        "f": {"0": 3, "1": 0},
        "statementMap": {
            "0": {"start": {"line": 11}},
            "1": {"start": {"line": 12}},
            "2": {"start": {"line": 20}},
        },
        "s": {"0": 3, "1": 0, "2": 0},
        "branchMap": {
            "0": {"line": 12, "loc": {"start": {"line": 12}}},
            "1": {"line": 21, "loc": {"start": {"line": 21}}},
        },
        "b": {"0": [2, 0], "1": [0, 0]},
    }


def test_dynamic_candidates_preserve_file_name_line_and_count(tmp_path: Path) -> None:
    trace = tmp_path / "calls.tsv"
    trace.write_text(
        "D\t/testbed/src/service.js\thelper\t10\n"
        "D\t/testbed/src/service.js\thelper\t10\n",
        encoding="utf-8",
    )

    assert _dynamic_candidates(trace) == {
        ("/testbed/src/service.js", "helper", 10): 2
    }


def test_called_function_coverage_attaches_and_aggregates_istanbul_data(
    tmp_path: Path,
) -> None:
    report = tmp_path / "coverage-final.json"
    report.write_text(
        json.dumps({"/testbed/src/service.js": _coverage_entry()}),
        encoding="utf-8",
    )
    dynamic = _dynamic_candidates(_write_trace(tmp_path, "helper", 10))

    executed, static_only, aggregate = _called_function_coverage(
        report, dynamic, {"helper"}
    )

    assert executed[0]["call_count"] == 1
    assert static_only == []
    assert executed[0]["coverage"]["line"] == {
        "covered": 1, "total": 2, "rate": 0.5
    }
    assert executed[0]["coverage"]["branch"] == {
        "covered": 1, "total": 2, "rate": 0.5
    }
    assert aggregate == {
        "line": {"covered": 1, "total": 2, "rate": 0.5},
        "branch": {"covered": 1, "total": 2, "rate": 0.5},
        "matched_function_count": 1,
        "unmatched_function_count": 0,
    }


def test_called_function_coverage_reports_unmatched_function(tmp_path: Path) -> None:
    report = tmp_path / "coverage-final.json"
    report.write_text(
        json.dumps({"/testbed/src/service.js": _coverage_entry()}),
        encoding="utf-8",
    )
    dynamic = _dynamic_candidates(_write_trace(tmp_path, "missing", 30))

    executed, _, aggregate = _called_function_coverage(report, dynamic, {"missing"})

    assert executed[0]["coverage"] is None
    assert executed[0]["coverage_status"] == "not_present_in_istanbul_report"
    assert aggregate["matched_function_count"] == 0
    assert aggregate["unmatched_function_count"] == 1
    assert aggregate["line"]["rate"] is None
    assert aggregate["branch"]["rate"] is None


def test_called_function_coverage_matches_named_arrow_reported_as_anonymous(
    tmp_path: Path,
) -> None:
    entry = _coverage_entry()
    entry["fnMap"]["0"]["name"] = "(anonymous_0)"
    report = tmp_path / "coverage-final.json"
    report.write_text(
        json.dumps({"/testbed/src/service.js": entry}), encoding="utf-8"
    )
    dynamic = _dynamic_candidates(_write_trace(tmp_path, "helper", 10))

    executed, _, aggregate = _called_function_coverage(report, dynamic, {"helper"})

    assert executed[0]["coverage"]["first_line"] == 10
    assert aggregate["matched_function_count"] == 1
    assert aggregate["unmatched_function_count"] == 0


def test_called_function_coverage_includes_unexecuted_static_candidate(
    tmp_path: Path,
) -> None:
    report = tmp_path / "coverage-final.json"
    report.write_text(
        json.dumps({"/testbed/src/service.js": _coverage_entry()}),
        encoding="utf-8",
    )
    dynamic = _dynamic_candidates(_write_trace(tmp_path, "helper", 10))

    _, static_only, aggregate = _called_function_coverage(
        report, dynamic, {"helper", "other"}
    )

    assert static_only[0]["function"] == "other"
    assert static_only[0]["coverage"]["execution_count"] == 0
    assert aggregate == {
        "line": {"covered": 1, "total": 3, "rate": 1 / 3},
        "branch": {"covered": 1, "total": 4, "rate": 0.25},
        "matched_function_count": 2,
        "unmatched_function_count": 0,
    }


def test_static_named_arrow_matches_anonymous_istanbul_entry_by_location(
    tmp_path: Path,
) -> None:
    entry = _coverage_entry()
    entry["fnMap"]["1"]["name"] = "(anonymous_1)"
    report = tmp_path / "coverage-final.json"
    report.write_text(
        json.dumps({"/testbed/src/service.js": entry}), encoding="utf-8"
    )

    _, static_only, aggregate = _called_function_coverage(
        report,
        Counter(),
        {"other"},
        {"other": (("/testbed/src/service.js", 20),)},
    )

    assert static_only[0]["coverage"]["execution_count"] == 0
    assert aggregate["line"] == {"covered": 0, "total": 1, "rate": 0.0}
    assert aggregate["branch"] == {"covered": 0, "total": 2, "rate": 0.0}
    assert aggregate["matched_function_count"] == 1


def _write_trace(tmp_path: Path, name: str, line: int) -> Path:
    trace = tmp_path / f"{name}.tsv"
    trace.write_text(
        f"D\t/testbed/src/service.js\t{name}\t{line}\n", encoding="utf-8"
    )
    return trace
