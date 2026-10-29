"""Isolated pytest execution and JSON-report interpretation for Python dual filtering."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PytestSummary:
    report_present: bool = False
    collection_ok: bool = False
    executed: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    assertion_failures: list[dict] = field(default_factory=list)
    runtime_errors: list[dict] = field(default_factory=list)
    collection_errors: list[dict] = field(default_factory=list)
    no_tests: bool = True

    @property
    def clean(self) -> bool:
        return (
            self.report_present
            and self.collection_ok
            and self.executed > 0
            and self.failed == 0
            and self.errors == 0
            and not self.collection_errors
        )

    def to_dict(self):
        return {
            "report_present": self.report_present,
            "collection_ok": self.collection_ok,
            "executed": self.executed,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "assertion_failures": self.assertion_failures,
            "runtime_errors": self.runtime_errors,
            "collection_errors": self.collection_errors,
            "no_tests": self.no_tests,
            "clean": self.clean,
        }


@dataclass
class PytestRun:
    returncode: int
    stdout: str
    stderr: str
    report_path: str
    report: dict | None
    timed_out: bool = False
    infrastructure_error: str | None = None

    def to_dict(self):
        return {
            "returncode": self.returncode,
            "stdout": self.stdout[-4000:],
            "stderr": self.stderr[-4000:],
            "report_path": self.report_path,
            "timed_out": self.timed_out,
            "infrastructure_error": self.infrastructure_error,
        }


def _failure_message(test):
    call = test.get("call") or {}
    setup = test.get("setup") or {}
    teardown = test.get("teardown") or {}
    return "\n".join(
        part for part in (
            call.get("longrepr") or call.get("crash", {}).get("message"),
            setup.get("longrepr") or setup.get("crash", {}).get("message"),
            teardown.get("longrepr") or teardown.get("crash", {}).get("message"),
        ) if part
    )[:8000]


def parse_pytest_report(report: dict | None, generated_test_path: str = "") -> PytestSummary:
    if not isinstance(report, dict):
        return PytestSummary()
    summary = report.get("summary") or {}
    tests = report.get("tests") or []
    collectors = report.get("collectors") or []
    target = str(generated_test_path).replace(os.sep, "/")
    relevant_tests = [
        test for test in tests
        if not target or target in str(test.get("nodeid", "")).replace(os.sep, "/")
    ]
    relevant_collectors = [
        c for c in collectors
        if not target or target in str(c.get("nodeid", "")).replace(os.sep, "/")
    ]
    if not relevant_tests and not target:
        relevant_tests = tests
    if not relevant_collectors and not target:
        relevant_collectors = collectors

    result = PytestSummary(report_present=True)
    result.executed = len(relevant_tests)
    for test in relevant_tests:
        outcome = test.get("outcome", "")
        if outcome == "passed":
            result.passed += 1
        elif outcome == "skipped":
            result.skipped += 1
        elif outcome == "failed":
            result.failed += 1
            item = {"nodeid": test.get("nodeid", ""), "message": _failure_message(test)}
            if (test.get("call") or {}).get("crash") or (test.get("call") or {}).get("longrepr"):
                result.assertion_failures.append(item)
            else:
                result.runtime_errors.append(item)
        elif outcome == "error":
            result.errors += 1
            result.runtime_errors.append({"nodeid": test.get("nodeid", ""), "message": _failure_message(test)})

    result.no_tests = result.executed == 0
    result.collection_ok = bool(relevant_collectors) and not any(
        c.get("outcome") == "failed" or c.get("result") is None and c.get("error")
        for c in relevant_collectors
    )
    if not relevant_collectors and result.executed:
        result.collection_ok = True
    for collector in relevant_collectors:
        if collector.get("outcome") == "failed" or collector.get("error"):
            result.collection_errors.append({
                "nodeid": collector.get("nodeid", ""),
                "message": collector.get("longrepr") or collector.get("error", ""),
            })
    # pytest's summary can include tests omitted from a narrowed report; use it
    # only as a fallback when the report has no per-test entries.
    if not relevant_tests and summary:
        result.failed = int(summary.get("failed", 0) or 0)
        result.errors = int(summary.get("error", 0) or 0)
        result.skipped = int(summary.get("skipped", 0) or 0)
    return result


def run_pytest(project_root: Path, test_file: Path, report_path: Path, *,
               python_executable: str = "python", timeout_seconds: int = 120,
               extra_env: dict[str, str] | None = None) -> PytestRun:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)
        env["PYTHONPATH"] = os.pathsep.join(
            p for p in (str(project_root), env.get("PYTHONPATH", "")) if p
        )
        command = [
            python_executable, "-m", "pytest",
            "--import-mode=importlib",
            "--continue-on-collection-errors",
            f"--timeout={timeout_seconds}",
            "-q", "--disable-warnings", "--tb=no",
            "--json-report", f"--json-report-file={report_path}",
            str(test_file),
        ]
        completed = subprocess.run(
            command, cwd=project_root, env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout_seconds + 30, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return PytestRun(-1, str(exc.stdout or ""), str(exc.stderr or ""), str(report_path), None, True, "pytest timeout")
    except OSError as exc:
        return PytestRun(-1, "", "", str(report_path), None, False, f"pytest launch failed: {exc}")

    report = None
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return PytestRun(completed.returncode, completed.stdout, completed.stderr, str(report_path), None, False, f"invalid pytest report: {exc}")
    return PytestRun(completed.returncode, completed.stdout, completed.stderr, str(report_path), report)


def build_repair_feedback(summary: PytestSummary, run: PytestRun) -> str:
    if run.infrastructure_error:
        return f"pytest infrastructure error: {run.infrastructure_error}\n{run.stderr[-4000:]}"
    parts = []
    if summary.collection_errors:
        parts.append("Collection errors:\n" + json.dumps(summary.collection_errors, ensure_ascii=False, indent=2))
    if summary.assertion_failures:
        parts.append("Assertion failures:\n" + json.dumps(summary.assertion_failures, ensure_ascii=False, indent=2))
    if summary.runtime_errors:
        parts.append("Runtime/setup/teardown errors:\n" + json.dumps(summary.runtime_errors, ensure_ascii=False, indent=2))
    if summary.no_tests:
        parts.append("No tests were executed.")
    if not parts:
        parts.append(run.stderr[-4000:] or run.stdout[-4000:] or "pytest failed without a report")
    return "\n\n".join(parts)
