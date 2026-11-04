from __future__ import annotations

import sys
from pathlib import Path


EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"
sys.path.insert(0, str(EVAL_DIR))

from eval_java_dynamic_calls import _aggregate_candidate_coverage  # noqa: E402


def test_aggregate_candidate_coverage_sums_unique_methods() -> None:
    first = ("example/Service", "first", "()V")
    second = ("example/Service", "second", "(I)I")
    methods = {
        first: {
            "line": {"covered": 3, "total": 4},
            "branch": {"covered": 1, "total": 2},
        },
        second: {
            "line": {"covered": 2, "total": 6},
            "branch": {"covered": 3, "total": 4},
        },
    }

    result = _aggregate_candidate_coverage(methods, {first, second})

    assert result == {
        "line": {"covered": 5, "total": 10, "rate": 0.5},
        "branch": {"covered": 4, "total": 6, "rate": 4 / 6},
        "matched_function_count": 2,
        "unmatched_function_count": 0,
    }


def test_aggregate_candidate_coverage_reports_missing_jacoco_methods() -> None:
    present = ("example/Service", "present", "()V")
    missing = ("example/Service", "missing", "()V")
    methods = {
        present: {
            "line": {"covered": 1, "total": 2},
            "branch": {"covered": 0, "total": 0},
        }
    }

    result = _aggregate_candidate_coverage(methods, {present, missing})

    assert result["line"] == {"covered": 1, "total": 2, "rate": 0.5}
    assert result["branch"] == {"covered": 0, "total": 0, "rate": None}
    assert result["matched_function_count"] == 1
    assert result["unmatched_function_count"] == 1


def test_aggregate_candidate_coverage_handles_empty_candidates() -> None:
    result = _aggregate_candidate_coverage({}, set())

    assert result["line"] == {"covered": 0, "total": 0, "rate": None}
    assert result["branch"] == {"covered": 0, "total": 0, "rate": None}
    assert result["matched_function_count"] == 0
    assert result["unmatched_function_count"] == 0
