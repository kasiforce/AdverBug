#!/usr/bin/env python3
"""Evaluate generated Jest tests in isolated Docker containers.

Every dataset item is evaluated in a fresh container.  The generated test and
its generated configuration files are copied into the clean project checkout.
The test is first run without instrumentation to determine pass/fail, then run
again with target-file-only coverage instrumentation.  Istanbul coverage maps
are retained per item and merged as execution unions for both all executed
tests and the subset whose tests pass.

The JSON layout mirrors ``eval_java.py`` and ``eval_py.py`` so downstream
aggregation can use the same compile/test/coverage fields across languages.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any


EVAL_DIR = Path(__file__).resolve().parent
INSTANCE_SCRIPT = EVAL_DIR / "js_eval_container.sh"
MERGE_SCRIPT = EVAL_DIR / "js_merge_coverage.js"


def _safe_relative_path(value: str, field: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} must be a safe project-relative path: {value!r}")
    return path


def _safe_name(value: str, max_length: int = 70) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "item"
    return cleaned[:max_length]


def _instance_id(index: int, item: dict[str, Any]) -> str:
    identity = "|".join(
        str(item.get(key, ""))
        for key in ("src_file", "class_name", "name", "start_line")
    )
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:10]
    return f"{index:04d}_{_safe_name(str(item.get('name', 'function')), 35)}_{digest}"


def _file_slug(src_file: str) -> str:
    digest = hashlib.sha1(src_file.encode("utf-8")).hexdigest()[:10]
    return f"{_safe_name(Path(src_file).stem, 40)}_{digest}"


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _atomic_json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _metric(total: int, covered: int) -> dict[str, Any]:
    return {
        "total": total,
        "covered": covered,
        "rate": covered / total if total else 0.0,
    }


def _normalize_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    if normalized.startswith("/testbed/"):
        normalized = normalized[len("/testbed/") :]
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lstrip("/")


def _source_key(item: dict[str, Any]) -> str:
    src_file = str(item.get("src_file", ""))
    project_root = str(item.get("project_root", "")).rstrip("/\\")
    if project_root and src_file.startswith(project_root):
        src_file = src_file[len(project_root) :].lstrip("/\\")
    return _normalize_path(src_file)


def _find_file_entry(
    coverage: dict[str, Any], item: dict[str, Any]
) -> tuple[str | None, dict[str, Any] | None]:
    wanted = _source_key(item)
    normalized = {
        _normalize_path(str(key)): (str(key), value)
        for key, value in coverage.items()
        if isinstance(value, dict)
    }
    if wanted in normalized:
        return normalized[wanted]
    matches = [
        pair
        for key, pair in normalized.items()
        if key.endswith("/" + wanted) or wanted.endswith("/" + key)
    ]
    if len(matches) == 1:
        return matches[0]
    return None, None


def _counter(entry: dict[str, Any], key: str) -> dict[str, int]:
    value = entry.get(key) or {}
    return {str(name): int(hit or 0) for name, hit in value.items()}


def _branch_counter(entry: dict[str, Any]) -> dict[str, list[int]]:
    value = entry.get("b") or {}
    return {
        str(name): [int(hit or 0) for hit in hits]
        for name, hits in value.items()
        if isinstance(hits, list)
    }


def _statement_line_map(entry: dict[str, Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for key, location in (entry.get("statementMap") or {}).items():
        try:
            result[str(key)] = int(location["start"]["line"])
        except (KeyError, TypeError, ValueError):
            continue
    return result


def _file_metrics(entry: dict[str, Any]) -> dict[str, Any]:
    statements = _counter(entry, "s")
    functions = _counter(entry, "f")
    branches = _branch_counter(entry)
    line_hits: dict[int, int] = {}
    for key, line in _statement_line_map(entry).items():
        line_hits[line] = line_hits.get(line, 0) + statements.get(key, 0)
    branch_hits = [hit for hits in branches.values() for hit in hits]
    return {
        "line": _metric(len(line_hits), sum(hit > 0 for hit in line_hits.values())),
        "branch": _metric(len(branch_hits), sum(hit > 0 for hit in branch_hits)),
        "function": _metric(len(functions), sum(hit > 0 for hit in functions.values())),
        "statement": _metric(len(statements), sum(hit > 0 for hit in statements.values())),
    }


def _target_function_metrics(
    entry: dict[str, Any], item: dict[str, Any]
) -> dict[str, Any] | None:
    start = int(item.get("start_line") or 0)
    end = int(item.get("end_line") or 0)
    if start <= 0 or end < start:
        return None

    statements = _counter(entry, "s")
    line_hits: dict[int, int] = {}
    for key, line in _statement_line_map(entry).items():
        if start <= line <= end:
            line_hits[line] = line_hits.get(line, 0) + statements.get(key, 0)

    branch_hits: list[int] = []
    branches = _branch_counter(entry)
    for key, branch in (entry.get("branchMap") or {}).items():
        try:
            line = int(branch.get("line") or branch["loc"]["start"]["line"])
        except (KeyError, TypeError, ValueError):
            continue
        if start <= line <= end:
            branch_hits.extend(branches.get(str(key), []))

    class_name = str(item.get("class_name") or "")
    name = str(item.get("name") or "")
    requested = f"{class_name}.{name}" if class_name else name
    return {
        "line": _metric(len(line_hits), sum(hit > 0 for hit in line_hits.values())),
        "branch": _metric(len(branch_hits), sum(hit > 0 for hit in branch_hits)),
        "matched_methods": [
            {
                "class": class_name,
                "method": requested,
                "first_line": start,
                "last_line": end,
                "match_source": "source_range",
            }
        ],
        "ambiguous_match": False,
    }


def parse_instance_coverage(path: Path, item: dict[str, Any]) -> dict[str, Any]:
    empty = {"report_found": False, "target_file": None, "target_function": None}
    if not path.is_file():
        return empty
    try:
        coverage = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {**empty, "parse_error": str(error)}
    file_key, entry = _find_file_entry(coverage, item)
    if entry is None:
        return {"report_found": True, "target_file": None, "target_function": None}
    return {
        "report_found": True,
        "target_file": {
            "file_key": _normalize_path(file_key or _source_key(item)),
            **_file_metrics(entry),
        },
        "target_function": _target_function_metrics(entry, item),
    }


def parse_jest_report(path: Path) -> dict[str, Any]:
    empty = {
        "total": 0,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "passed": 0,
        "pass_rate": 0.0,
        "report_count": 0,
        "parse_errors": [],
    }
    if not path.is_file():
        return empty
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        total = int(report.get("numTotalTests", 0) or 0)
        passed = int(report.get("numPassedTests", 0) or 0)
        failures = int(report.get("numFailedTests", 0) or 0)
        skipped = int(
            (report.get("numPendingTests", 0) or 0)
            + (report.get("numTodoTests", 0) or 0)
        )
        errors = int(report.get("numRuntimeErrorTestSuites", 0) or 0)
        if total == 0:
            total = passed + failures + skipped
        return {
            "total": total,
            "failures": failures,
            "errors": errors,
            "skipped": skipped,
            "passed": passed,
            "pass_rate": passed / total if total else 0.0,
            "report_count": 1,
            "parse_errors": [],
            "total_suites": int(report.get("numTotalTestSuites", 0) or 0),
            "passed_suites": int(report.get("numPassedTestSuites", 0) or 0),
            "failed_suites": int(report.get("numFailedTestSuites", 0) or 0),
        }
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {**empty, "parse_errors": [str(error)]}


def _stage_item(item: dict[str, Any], stage_dir: Path) -> None:
    test_path = _safe_relative_path(str(item.get("test_file", "")), "test_file")
    src_path = _safe_relative_path(_source_key(item), "src_file")
    generated = item.get("generated_tests") or []
    if isinstance(generated, str):
        generated = [generated]
    code = "\n\n".join(str(part) for part in generated if str(part).strip()).strip()
    if not code:
        raise ValueError("generated_tests is empty")
    _write_text(stage_dir / "files" / Path(*test_path.parts), code + "\n")
    _write_text(stage_dir / "test_file.txt", test_path.as_posix() + "\n")
    _write_text(stage_dir / "src_file.txt", src_path.as_posix() + "\n")
    for config in item.get("generated_config_files") or []:
        if not isinstance(config, dict) or not config.get("path"):
            continue
        path = _safe_relative_path(str(config["path"]), "generated_config_files.path")
        _write_text(stage_dir / "files" / Path(*path.parts), str(config.get("code", "")))


def _read_int(path: Path, default: int | None = None) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return default


def _copy_if_present(source: Path, destination: Path) -> str | None:
    if not source.is_file() or source.stat().st_size == 0:
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination.as_posix()


def evaluate_instance(
    *,
    image: str,
    item: dict[str, Any],
    index: int,
    output_dir: Path,
    timeout: int,
    test_timeout: int,
    coverage_provider: str,
    keep_logs: bool,
    install_eval_deps: bool,
) -> dict[str, Any]:
    instance_id = _instance_id(index, item)
    suffix = hashlib.sha1(str(output_dir).encode("utf-8")).hexdigest()[:8]
    container_name = f"adverbug-js-eval-{suffix}-{instance_id}"[:120]
    started = time.monotonic()
    evaluation: dict[str, Any] = {
        "instance_id": instance_id,
        "compile_pass": False,
        "test_pass": False,
        "failure_stage": None,
    }

    with tempfile.TemporaryDirectory(prefix="js-eval-input-") as stage_name, tempfile.TemporaryDirectory(
        prefix="js-eval-output-"
    ) as run_name:
        stage_dir = Path(stage_name)
        run_dir = Path(run_name)
        try:
            _stage_item(item, stage_dir)
        except (ValueError, OSError) as error:
            evaluation.update(failure_stage="input", failure_message=str(error))
            evaluation["duration_seconds"] = time.monotonic() - started
            return evaluation

        command = [
            "docker", "run", "--rm", "--name", container_name,
            "-v", f"{stage_dir}:/eval-input:ro",
            "-v", f"{run_dir}:/results",
            "-v", f"{INSTANCE_SCRIPT}:/eval/js_eval_container.sh:ro",
            "-e", f"INSTALL_EVAL_DEPS={1 if install_eval_deps else 0}",
            "-e", f"JEST_TEST_TIMEOUT_MS={test_timeout * 1000}",
            "-e", f"JEST_COVERAGE_PROVIDER={coverage_provider}",
            image, "bash", "/eval/js_eval_container.sh",
        ]
        completed: subprocess.CompletedProcess[str] | None
        try:
            completed = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
            evaluation["container_exit_code"] = completed.returncode
        except subprocess.TimeoutExpired as error:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                text=True, capture_output=True, check=False,
            )
            completed = None
            evaluation.update(failure_stage="timeout", failure_message=f"Exceeded {timeout} seconds")
            captured = (error.stdout or "") + "\n" + (error.stderr or "")
            _write_text(output_dir / "logs" / f"{instance_id}.log", captured)
        except KeyboardInterrupt:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                text=True, capture_output=True, check=False,
            )
            raise

        syntax_exit = _read_int(run_dir / "syntax_exit_code.txt")
        test_exit = _read_int(run_dir / "test_exit_code.txt")
        coverage_exit = _read_int(run_dir / "coverage_exit_code.txt")
        evaluation["syntax_exit_code"] = syntax_exit
        evaluation["test_exit_code"] = test_exit
        evaluation["coverage_exit_code"] = coverage_exit
        evaluation["syntax"] = {
            "parser": "node-check",
            "parser_available": syntax_exit is not None and syntax_exit != 127,
            "has_code": True,
            "correct": syntax_exit == 0,
        }

        summary = parse_jest_report(run_dir / "report.json")
        evaluation["test_summary"] = summary
        report_loaded = summary["report_count"] == 1 and not summary["parse_errors"]
        evaluation["compile_pass"] = bool(report_loaded and summary["errors"] == 0)
        evaluation["compile_exit_code"] = 0 if evaluation["compile_pass"] else 1
        evaluation["test_pass"] = bool(
            evaluation["compile_pass"]
            and test_exit == 0
            and summary["total"] > 0
            and summary["passed"] > 0
            and summary["failures"] == 0
        )

        if evaluation["failure_stage"] is None:
            if test_exit is None:
                evaluation["failure_stage"] = "infrastructure"
            elif not evaluation["compile_pass"]:
                evaluation["failure_stage"] = "compile"
            elif not evaluation["test_pass"]:
                evaluation["failure_stage"] = "test"

        coverage_source = run_dir / "coverage" / "coverage-final.json"
        coverage_dest = output_dir / "exec" / f"{instance_id}.json"
        saved = _copy_if_present(coverage_source, coverage_dest)
        evaluation["coverage_data"] = (
            str(coverage_dest.relative_to(output_dir)) if saved else None
        )
        evaluation["coverage_collection_pass"] = bool(coverage_exit == 0 and saved)
        evaluation["coverage"] = parse_instance_coverage(coverage_source, item)

        should_keep_log = (
            keep_logs
            or not evaluation["compile_pass"]
            or not evaluation["test_pass"]
            or not evaluation["coverage_collection_pass"]
            or not evaluation["coverage_data"]
        )
        if should_keep_log:
            parts: list[str] = []
            if completed is not None:
                parts.extend([
                    "=== docker stdout ===\n" + completed.stdout,
                    "=== docker stderr ===\n" + completed.stderr,
                ])
            for name in ("dependencies.log", "syntax.log", "test.log", "coverage.log"):
                path = run_dir / name
                if path.is_file():
                    parts.append(
                        f"=== {name} ===\n" + path.read_text(encoding="utf-8", errors="replace")
                    )
            destination = output_dir / "logs" / f"{instance_id}.log"
            _write_text(destination, "\n".join(parts))
            evaluation["log"] = str(destination.relative_to(output_dir))

    evaluation["duration_seconds"] = time.monotonic() - started
    return evaluation


def merge_coverage(
    image: str,
    output_dir: Path,
    results: list[dict[str, Any]],
    kind: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    eligible: list[tuple[dict[str, Any], Path]] = []
    for item in results:
        evaluation = item.get("evaluation") or {}
        relative = evaluation.get("coverage_data")
        if relative and (kind == "all_executed" or evaluation.get("test_pass") is True):
            eligible.append((item, output_dir / str(relative)))

    merge_dir = output_dir / "coverage" / kind
    merged_path = merge_dir / "coverage-final.json"
    errors: list[str] = []
    merger_details: dict[str, Any] = {"merger": "istanbul-lib-coverage"}
    merged: dict[str, Any] = {}
    if eligible:
        manifest_path = merge_dir / "merge-manifest.json"
        manifest = {
            "kind": kind,
            "inputs": [f"/coverage-work/{path.relative_to(output_dir).as_posix()}" for _, path in eligible],
        }
        _atomic_json_dump(manifest_path, manifest)
        command = [
            "docker", "run", "--rm", "--network", "none",
            "-v", f"{output_dir}:/coverage-work",
            "-v", f"{MERGE_SCRIPT}:/eval/js_merge_coverage.js:ro",
            image,
            "node", "/eval/js_merge_coverage.js",
            f"/coverage-work/{manifest_path.relative_to(output_dir).as_posix()}",
            f"/coverage-work/{merged_path.relative_to(output_dir).as_posix()}",
        ]
        try:
            completed = subprocess.run(
                command, text=True, capture_output=True, timeout=600, check=False
            )
            if completed.returncode != 0:
                details = (completed.stderr or completed.stdout).strip()
                errors.append(
                    f"istanbul-lib-coverage exited {completed.returncode}: {details}"
                )
            else:
                output_lines = [line for line in completed.stdout.splitlines() if line.strip()]
                if output_lines:
                    merger_details.update(json.loads(output_lines[-1]))
                merged = json.loads(merged_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
            errors.append(f"istanbul-lib-coverage merge failed: {error}")
    else:
        _atomic_json_dump(merged_path, {})

    source_files = sorted({_source_key(item) for item, _ in eligible if _source_key(item)})
    file_coverage: dict[str, Any] = {}
    for src_file in sorted({_source_key(item) for item in results if _source_key(item)}):
        _, entry = _find_file_entry(merged, {"src_file": src_file})
        base = {"module": ".", "file_key": src_file}
        if entry is None:
            file_coverage[src_file] = {"report_found": False, **base}
        else:
            file_coverage[src_file] = {"report_found": True, **base, **_file_metrics(entry)}
            _atomic_json_dump(
                merge_dir / "files" / f"{_file_slug(src_file)}.json",
                {src_file: entry},
            )

    status = {
        "kind": kind,
        "exec_count": len(eligible),
        "success": bool(eligible) and not errors,
        "modules": {".": "root"} if source_files else {},
        "file_group_count": len(set(source_files)),
        **merger_details,
    }
    if not eligible:
        status["error"] = "No coverage files were eligible for merging"
    elif errors:
        status["errors"] = errors
    return status, file_coverage


def _build_image(dockerfile: Path, context: Path, image: str) -> None:
    subprocess.run(
        ["docker", "build", "-t", image, "-f", str(dockerfile), str(context)],
        check=True,
    )


def evaluate_dataset(args: argparse.Namespace) -> dict[str, Any]:
    data_file = args.data_file.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    evaluated_path = output_dir / "evaluated_results.json"
    source_items = json.loads(data_file.read_text(encoding="utf-8"))
    if not isinstance(source_items, list):
        raise ValueError("The generated-test JSON must contain a top-level list")

    if args.resume and evaluated_path.is_file():
        previous = json.loads(evaluated_path.read_text(encoding="utf-8"))
        if not isinstance(previous, list) or len(previous) != len(source_items):
            raise ValueError("Cannot resume: evaluated_results.json does not match input length")
        results = []
        for source, old in zip(source_items, previous):
            refreshed = dict(source)
            if "evaluation" in old:
                refreshed["evaluation"] = old["evaluation"]
            results.append(refreshed)
    else:
        results = source_items
    _atomic_json_dump(evaluated_path, results)

    stop = len(results) if args.limit is None else min(len(results), args.start + args.limit)
    pending: list[int] = []
    for index in range(args.start, stop):
        existing = results[index].get("evaluation") or {}
        data = existing.get("coverage_data")
        if args.resume and not args.redo_existing and existing.get("compile_exit_code") is not None:
            finished_without_coverage = existing.get("compile_pass") is False
            finished_with_coverage = bool(data and (output_dir / str(data)).is_file())
            if finished_without_coverage or finished_with_coverage:
                print(f"[{index + 1}/{len(results)}] resume: {results[index].get('name')}", flush=True)
                continue
        pending.append(index)

    def run_index(index: int) -> tuple[int, dict[str, Any]]:
        print(
            f"[{index + 1}/{len(results)}] evaluating {results[index].get('name')} in a fresh container",
            flush=True,
        )
        return index, evaluate_instance(
            image=args.image,
            item=results[index],
            index=index,
            output_dir=output_dir,
            timeout=args.timeout,
            test_timeout=args.test_timeout,
            coverage_provider=args.coverage_provider,
            keep_logs=args.keep_logs,
            install_eval_deps=not args.no_install_eval_deps,
        )

    if args.workers == 1:
        for index in pending:
            completed_index, evaluation = run_index(index)
            results[completed_index]["evaluation"] = evaluation
            results[completed_index]["syntax_evaluation"] = evaluation.get("syntax", {})
            _atomic_json_dump(evaluated_path, results)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(run_index, index) for index in pending]
            for future in concurrent.futures.as_completed(futures):
                index, evaluation = future.result()
                results[index]["evaluation"] = evaluation
                results[index]["syntax_evaluation"] = evaluation.get("syntax", {})
                _atomic_json_dump(evaluated_path, results)

    merge_summaries: dict[str, Any] = {}
    file_coverage: dict[str, Any] = {}
    if not args.no_merge:
        status, coverage = merge_coverage(args.image, output_dir, results, "all_executed")
        merge_summaries["all_executed"] = status
        file_coverage["all_executed"] = coverage

        all_count = sum(
            bool((item.get("evaluation") or {}).get("coverage_data")) for item in results
        )
        passing_count = sum(
            bool((item.get("evaluation") or {}).get("coverage_data"))
            and (item.get("evaluation") or {}).get("test_pass") is True
            for item in results
        )
        if all_count > 0 and all_count == passing_count and status.get("success") is True:
            source_dir = output_dir / "coverage" / "all_executed"
            passing_dir = output_dir / "coverage" / "passing"
            passing_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_dir / "coverage-final.json", passing_dir / "coverage-final.json")
            if (source_dir / "files").is_dir():
                shutil.copytree(source_dir / "files", passing_dir / "files", dirs_exist_ok=True)
            reused_status = json.loads(json.dumps(status))
            reused_status.update(kind="passing", reused_from="all_executed")
            merge_summaries["passing"] = reused_status
            file_coverage["passing"] = json.loads(json.dumps(coverage))
        else:
            status, coverage = merge_coverage(args.image, output_dir, results, "passing")
            merge_summaries["passing"] = status
            file_coverage["passing"] = coverage

    evaluated = [item.get("evaluation") or {} for item in results if item.get("evaluation")]
    syntax_results = [
        item.get("syntax_evaluation") or (item.get("evaluation") or {}).get("syntax") or {}
        for item in results
    ]
    syntax_known = [entry for entry in syntax_results if entry.get("parser_available") is True]
    syntax_correct = sum(entry.get("correct") is True for entry in syntax_known)
    summary = {
        "input": str(data_file),
        "image": args.image,
        "coverage_provider": args.coverage_provider,
        "target_count": len(source_items),
        "evaluated_count": len(evaluated),
        "compile_pass_count": sum(entry.get("compile_pass") is True for entry in evaluated),
        "test_pass_count": sum(entry.get("test_pass") is True for entry in evaluated),
        "exec_count": sum(bool(entry.get("coverage_data")) for entry in evaluated),
        "syntax": {
            "parser": "node-check",
            "parser_available": bool(syntax_known),
            "total": len(syntax_known),
            "correct": syntax_correct,
            "incorrect": len(syntax_known) - syntax_correct,
            "correct_rate": syntax_correct / len(syntax_known) if syntax_known else 0.0,
        },
        "merge": merge_summaries,
    }
    _atomic_json_dump(evaluated_path, results)
    _atomic_json_dump(output_dir / "file_coverage.json", file_coverage)
    _atomic_json_dump(output_dir / "summary.json", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate each generated Jest test in a fresh container and merge target-only coverage."
    )
    parser.add_argument("--data-file", type=Path, required=True, help="Generated-test JSON")
    parser.add_argument("--image", help="Prebuilt project image")
    parser.add_argument("--dockerfile", type=Path, help="Build an image from this Dockerfile first")
    parser.add_argument("--build-context", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=1200, help="Seconds per function")
    parser.add_argument("--test-timeout", type=int, default=60, help="Seconds per Jest test case")
    parser.add_argument(
        "--coverage-provider",
        choices=("v8", "babel"),
        default="babel",
        help="Jest coverage provider for the separate target-only coverage run (default: babel)",
    )
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--redo-existing", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--no-merge", action="store_true")
    parser.add_argument("--keep-logs", action="store_true")
    parser.add_argument(
        "--no-install-eval-deps",
        action="store_true",
        help="Require Jest to already exist in the image",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.image and not args.dockerfile:
        parser.error("one of --image or --dockerfile is required")
    if (
        args.start < 0
        or (args.limit is not None and args.limit < 1)
        or args.workers < 1
        or args.timeout < 1
        or args.test_timeout < 1
    ):
        parser.error("--start must be non-negative; --limit, --workers, and timeouts must be positive")
    if not args.image:
        args.image = f"adverbug-js-eval-{_safe_name(args.data_file.stem)}:latest"
    if args.dockerfile:
        _build_image(args.dockerfile.resolve(), args.build_context.resolve(), args.image)
    summary = evaluate_dataset(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
