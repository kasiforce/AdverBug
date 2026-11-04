from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def adver_dual(monkeypatch):
    # adver_dual is shipped as a container-side script rather than an installed
    # package, so import it through the repository's AdverBug directory.
    import sys

    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "AdverBug"))
    sys.modules.pop("adver_dual", None)
    import adver_dual as module

    return module


class FakeAgent:
    model_name = "fake-filter"

    def __init__(self, initial="class GeneratedTest {}", repaired=None):
        self.initial = initial
        self.repaired = repaired
        self.repair_calls = []
        self.compile_repair_calls = []

    def generate_tests(self, entry, bug_code):
        return self.initial

    def repair_false_positive(self, tests, error):
        self.repair_calls.append((tests, error))
        return self.repaired or tests

    def fix_compile(self, tests, error):
        self.compile_repair_calls.append((tests, error))
        return self.repaired or tests


def completed(returncode, output):
    return SimpleNamespace(returncode=returncode, stdout=output, stderr="")


def configure_common(monkeypatch, module):
    monkeypatch.setattr(
        module, "compile_test_suite",
        lambda agent, test_file, tests: (True, tests, "", []),
    )
    monkeypatch.setattr(module, "clean_surefire_reports", lambda: None)
    monkeypatch.setattr(
        module, "mvn", lambda *args, **kwargs: completed(0, "compiled original"),
    )


def test_bug_failure_is_detection_only_when_original_passes(
        tmp_path, monkeypatch, adver_dual):
    configure_common(monkeypatch, adver_dual)
    source = tmp_path / "Source.java"
    source.write_text("prefix BUGGY suffix", encoding="utf-8")
    test_file = tmp_path / "GeneratedTest.java"
    runs = iter([
        completed(1, "bug assertion failed"),
        completed(0, "original passed"),
    ])
    results = iter([
        {("GeneratedTest", "detectsBug"): "failed"},
        {("GeneratedTest", "detectsBug"): "passed"},
    ])
    monkeypatch.setattr(adver_dual, "run_compiled_test", lambda *a, **k: next(runs))
    monkeypatch.setattr(adver_dual, "parse_surefire_results", lambda: next(results))
    agent = FakeAgent()

    undetected, _tests, info = adver_dual.evaluate_filter_model(
        agent, {}, "BUGGY", str(source), "ORIGINAL", str(test_file),
        suite_retries=0,
    )

    assert undetected is False
    assert info["detected"] is True
    assert info["note"] == "differentially_detected_by: GeneratedTest.detectsBug"
    assert agent.repair_calls == []
    assert source.read_text(encoding="utf-8") == "prefix BUGGY suffix"


def test_original_failure_repairs_from_original_error_then_retests_bug(
        tmp_path, monkeypatch, adver_dual):
    configure_common(monkeypatch, adver_dual)
    source = tmp_path / "Source.java"
    source.write_text("prefix BUGGY suffix", encoding="utf-8")
    test_file = tmp_path / "GeneratedTest.java"
    runs = iter([
        completed(1, "bug failure must not be sent to repair"),
        completed(1, "original fixture failure"),
        completed(0, "repaired suite passed on bug"),
    ])
    results = iter([
        {("GeneratedTest", "badFixture"): "error"},
        {("GeneratedTest", "badFixture"): "error"},
        {("GeneratedTest", "fixedFixture"): "passed"},
    ])
    monkeypatch.setattr(adver_dual, "run_compiled_test", lambda *a, **k: next(runs))
    monkeypatch.setattr(adver_dual, "parse_surefire_results", lambda: next(results))
    agent = FakeAgent(repaired="class GeneratedTest { /* repaired */ }")

    undetected, tests, info = adver_dual.evaluate_filter_model(
        agent, {}, "BUGGY", str(source), "ORIGINAL", str(test_file),
        suite_retries=0,
    )

    assert undetected is True
    assert info["detected"] is False
    assert tests == "class GeneratedTest { /* repaired */ }"
    assert agent.repair_calls == [
        ("class GeneratedTest {}", "original fixture failure")]
    assert agent.compile_repair_calls == []
    assert source.read_text(encoding="utf-8") == "prefix BUGGY suffix"


def test_compile_failure_uses_existing_restricted_repair_not_closed_book(
        tmp_path, monkeypatch, adver_dual):
    source = tmp_path / "Source.java"
    source.write_text("prefix BUGGY suffix", encoding="utf-8")
    test_file = tmp_path / "GeneratedTest.java"
    compile_calls = iter([
        (False, "class GeneratedTest {}", "cannot find symbol Widget", []),
        (True, "class GeneratedTest { Widget value; }", "", []),
    ])
    monkeypatch.setattr(
        adver_dual, "compile_test_suite", lambda *a, **k: next(compile_calls))
    monkeypatch.setattr(adver_dual, "clean_surefire_reports", lambda: None)
    monkeypatch.setattr(
        adver_dual, "run_compiled_test", lambda *a, **k: completed(0, "passed"))
    monkeypatch.setattr(
        adver_dual, "parse_surefire_results",
        lambda: {("GeneratedTest", "works"): "passed"},
    )
    agent = FakeAgent(repaired="class GeneratedTest { Widget value; }")

    undetected, _tests, info = adver_dual.evaluate_filter_model(
        agent, {}, "BUGGY", str(source), "ORIGINAL", str(test_file),
        suite_retries=0,
    )

    assert undetected is True
    assert info["detected"] is False
    assert agent.compile_repair_calls == [
        ("class GeneratedTest {}", "cannot find symbol Widget")]
    assert agent.repair_calls == []
