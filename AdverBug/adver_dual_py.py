"""Python/pytest counterpart of AdverBug's dual-filter mutation workflow.

This entry point is additive and never edits the source project.  It copies the
project into disposable per-attempt workspaces, generates Python mutations and
pytest suites, and records every result.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

try:
    from .llm_config import LLMConfig
except ImportError:
    from llm_config import LLMConfig
try:
    from .py_filter_agent import PythonBugAgent, PythonFilterAgent, PythonSemanticJudge, syntax_check
    from .py_runner import build_repair_feedback, parse_pytest_report, run_pytest
except ImportError:
    from py_filter_agent import PythonBugAgent, PythonFilterAgent, PythonSemanticJudge, syntax_check
    from py_runner import build_repair_feedback, parse_pytest_report, run_pytest


@dataclass
class Options:
    source_project_root: Path | None
    work_dir: Path
    bug_model: str
    judge_model: str
    filter_model_a: str
    filter_model_b: str
    attempts: int = 5
    suite_retries: int = 2
    repair_rounds: int = 5
    pytest_timeout: int = 120
    python_executable: str = "python"
    keep_workspaces: bool = False


def atomic_json_dump(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def copy_project(source: Path, destination: Path):
    def ignore(directory, names):
        ignored = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", "build", "dist"}
        return [name for name in names if name in ignored]
    shutil.copytree(source, destination, ignore=ignore)


def resolve_source_root(entry: dict, explicit: Path | None):
    if explicit and explicit.is_dir():
        return explicit.resolve()
    recorded = entry.get("project_root")
    if recorded and Path(recorded).is_dir():
        return Path(recorded).resolve()
    return None


def validate_entry(entry: dict, source_root: Path):
    missing = [key for key in ("name", "src_file", "code") if not entry.get(key)]
    if missing:
        return False, f"missing input fields: {', '.join(missing)}"
    source_file = (source_root / entry["src_file"]).resolve()
    try:
        source_file.relative_to(source_root)
    except ValueError:
        return False, "source file escapes project root"
    if not source_file.is_file():
        return False, f"source file not found: {entry['src_file']}"
    return True, ""


def patch_function(source_file: Path, entry: dict, replacement: str):
    original = source_file.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    start = entry.get("start_line")
    end = entry.get("end_line")
    old = entry.get("code", "")
    if isinstance(start, int) and isinstance(end, int) and 1 <= start <= end <= len(lines):
        selected = "".join(lines[start - 1:end])
        if selected.strip() == old.strip() or old.strip() in selected:
            prefix = "".join(lines[:start - 1])
            suffix = "".join(lines[end:])
            newline = "\n" if original.endswith("\n") or not replacement.endswith("\n") else ""
            source_file.write_text(prefix + replacement.rstrip("\n") + newline + suffix, encoding="utf-8")
            return {"method": "line_range", "start_line": start, "end_line": end}
    occurrences = original.count(old) if old else 0
    if occurrences != 1:
        raise ValueError(f"ambiguous function replacement ({occurrences} exact matches)")
    source_file.write_text(original.replace(old, replacement, 1), encoding="utf-8")
    return {"method": "exact_text", "occurrences": occurrences}


def generated_test_path(project: Path, entry: dict, model_label: str, attempt: int):
    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in entry["name"])
    return project / ".adverbug_generated" / model_label / f"test_{safe_name}_{attempt}.py"


def run_filter(entry, original_code, buggy_code, source_project, model_label, agent, options, workspace):
    project = workspace / "project"
    copy_project(source_project, project)
    source_file = (project / entry["src_file"]).resolve()
    test_file = generated_test_path(project, entry, model_label, 0)
    test_file.parent.mkdir(parents=True, exist_ok=True)
    tests = ""
    repair_history = []
    for round_number in range(options.suite_retries + options.repair_rounds + 1):
        if not tests:
            tests = agent.generate_tests(entry, original_code, buggy_code)
        valid, syntax_error = syntax_check(tests)
        if not valid:
            feedback = syntax_error
        else:
            test_file.write_text(tests, encoding="utf-8")
            original_report = workspace / f"{model_label}_original_report.json"
            original_run = run_pytest(project, test_file, original_report,
                                       python_executable=options.python_executable,
                                       timeout_seconds=options.pytest_timeout)
            original_summary = parse_pytest_report(original_run.report, str(test_file.relative_to(project)))
            if not original_summary.clean:
                feedback = build_repair_feedback(original_summary, original_run)
            else:
                patch_info = patch_function(source_file, entry, buggy_code)
                buggy_report = workspace / f"{model_label}_buggy_report.json"
                buggy_run = run_pytest(project, test_file, buggy_report,
                                       python_executable=options.python_executable,
                                       timeout_seconds=options.pytest_timeout)
                buggy_summary = parse_pytest_report(buggy_run.report, str(test_file.relative_to(project)))
                detected = bool(original_summary.clean and buggy_summary.assertion_failures)
                return {
                    "model": agent.model,
                    "detected": detected,
                    "original_run": original_summary.to_dict() | {"process": original_run.to_dict()},
                    "buggy_run": buggy_summary.to_dict() | {"process": buggy_run.to_dict()},
                    "repair_rounds": round_number,
                    "test_code": tests,
                    "patch": patch_info,
                    "note": "assertion_failure_on_buggy" if detected else "passed_on_buggy",
                }
        repair_history.append({"round": round_number, "feedback": feedback, "test_code": tests})
        if round_number >= options.suite_retries + options.repair_rounds:
            return {
                "model": agent.model, "detected": False, "suite_generation_failed": True,
                "repair_rounds": round_number, "repair_history": repair_history,
                "note": "suite_generation_failed",
            }
        tests = agent.repair_tests(entry, original_code, buggy_code, tests, feedback)
    raise AssertionError("unreachable")


def process_entry(entry, index, agents, options):
    source_root = resolve_source_root(entry, options.source_project_root)
    base = copy.deepcopy(entry)
    if source_root is None:
        return base | {"status": "source_project_not_found", "filter_attempts": 0}, {
            "name": entry.get("name", f"entry-{index}"), "status": "source_project_not_found"
        }
    valid, reason = validate_entry(entry, source_root)
    if not valid:
        return base | {"status": "invalid_input", "reason": reason, "filter_attempts": 0}, {
            "name": entry.get("name", f"entry-{index}"), "status": "invalid_input", "reason": reason
        }

    options.work_dir.mkdir(parents=True, exist_ok=True)
    traces = []
    original_code = entry["code"]
    previous = ""
    for attempt in range(1, options.attempts + 1):
        attempt_dir = options.work_dir / f"entry-{index:03d}-attempt-{attempt:02d}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        try:
            bug = agents["bug"].enhance(entry, previous, json.dumps(traces[-1:], ensure_ascii=False)) if previous else agents["bug"].generate(entry)
            buggy = bug.get("buggy_code", "").strip()
            if not buggy or buggy.strip() == original_code.strip():
                traces.append({"attempt": attempt, "outcome": "bug_generation_empty"})
                continue
            syntax_ok, syntax_error = syntax_check(buggy)
            if not syntax_ok:
                traces.append({"attempt": attempt, "outcome": "bug_syntax_error", "error": syntax_error})
                previous = buggy
                continue
            filters = {}
            for label, model_agent in (("model_a", agents["filter_a"]), ("model_b", agents["filter_b"])):
                filters[label] = run_filter(
                    entry, original_code, buggy, source_root, label, model_agent, options,
                    attempt_dir / label,
                )
                if filters[label].get("suite_generation_failed"):
                    break
            if len(filters) != 2 or any(filters[k].get("detected") or filters[k].get("suite_generation_failed") for k in filters):
                traces.append({"attempt": attempt, "outcome": "filter_rejected", "filters": filters})
                previous = buggy
                continue
            tests = "\n\n".join(filters[k]["test_code"] for k in ("model_a", "model_b"))
            validation = agents["judge"].validate(entry, original_code, buggy, tests)
            if not validation.get("is_valid_bug"):
                traces.append({"attempt": attempt, "outcome": "equivalent_mutation", "validation": validation})
                previous = buggy
                continue
            accepted = base | {
                "buggy_code": [buggy], "bug_summary": bug.get("bug_summary", ""),
                "tests": [filters["model_a"]["test_code"], filters["model_b"]["test_code"]],
                "flag": "dual_filter_pass", "status": "accepted",
                "filter_results": {k: {key: value for key, value in v.items() if key != "test_code"} for k, v in filters.items()},
                "validation_result": validation, "filter_attempts": attempt,
            }
            traces.append({"attempt": attempt, "outcome": "accepted", "validation": validation})
            return accepted, {"name": entry.get("name", ""), "status": "accepted", "attempts": traces}
        except Exception as exc:
            traces.append({"attempt": attempt, "outcome": "error", "error": f"{type(exc).__name__}: {exc}"})
        finally:
            if not options.keep_workspaces:
                shutil.rmtree(attempt_dir, ignore_errors=True)
    return base | {"status": "rejected", "filter_attempts": options.attempts}, {
        "name": entry.get("name", ""), "status": "rejected", "attempts": traces
    }


def build_agents(options):
    def config(model):
        return LLMConfig(model_name=model)
    return {
        "bug": PythonBugAgent(config(options.bug_model)),
        "filter_a": PythonFilterAgent(config(options.filter_model_a)),
        "filter_b": PythonFilterAgent(config(options.filter_model_b)),
        "judge": PythonSemanticJudge(config(options.judge_model)),
    }


def main():
    parser = argparse.ArgumentParser(description="Python/pytest dual-filter mutation generation")
    parser.add_argument("--data-path", default="AdverBug/plotly_top5_extracted.json")
    parser.add_argument("--source-project-root", type=Path)
    parser.add_argument("--work-dir", type=Path, default=Path("AdverBug/adver_dual_py_work"))
    parser.add_argument("--results-path", type=Path, default=Path("AdverBug/final_results_py.json"))
    parser.add_argument("--stats-path", type=Path, default=Path("AdverBug/filter_stats_py.json"))
    parser.add_argument("--bug-model", default="gpt-5.4-mini")
    parser.add_argument("--judge-model", default="gpt-5.4-mini")
    parser.add_argument("--filter-model-a", default="gpt-5.4-mini")
    parser.add_argument("--filter-model-b", default="glm-5")
    parser.add_argument("--attempts", type=int, default=5)
    parser.add_argument("--suite-retries", type=int, default=2)
    parser.add_argument("--repair-rounds", type=int, default=5)
    parser.add_argument("--pytest-timeout", type=int, default=120)
    parser.add_argument("--python-executable", default="python")
    parser.add_argument("--keep-workspaces", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--start-index", type=int, default=0)
    args = parser.parse_args()
    entries = json.loads(Path(args.data_path).read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise SystemExit("data-path must contain a JSON list")
    entries = entries[args.start_index:]
    if args.limit is not None:
        entries = entries[:args.limit]
    options = Options(
        source_project_root=args.source_project_root,
        work_dir=args.work_dir,
        bug_model=args.bug_model,
        judge_model=args.judge_model,
        filter_model_a=args.filter_model_a,
        filter_model_b=args.filter_model_b,
        attempts=args.attempts,
        suite_retries=args.suite_retries,
        repair_rounds=args.repair_rounds,
        pytest_timeout=args.pytest_timeout,
        python_executable=args.python_executable,
        keep_workspaces=args.keep_workspaces,
    )
    agents = build_agents(options)
    results, stats = [], []
    for index, entry in enumerate(entries, args.start_index):
        result, trace = process_entry(entry, index, agents, options)
        stats.append(trace)
        if result.get("status") == "accepted":
            results.append(result)
        atomic_json_dump(args.results_path, results)
        atomic_json_dump(args.stats_path, stats)
        print(f"[{index}] {entry.get('name', '')}: {result.get('status')}", flush=True)


if __name__ == "__main__":
    main()
