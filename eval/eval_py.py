#!/usr/bin/env python3
"""Evaluate generated Python tests in isolated Docker containers.

Each benchmark item is collected and executed in a fresh container. Its raw
coverage.py data is copied to the host. After all items finish, coverage data
is combined as execution unions (never by averaging percentages), both for all
executed tests and for the subset whose tests pass.

The output layout and metric-bearing JSON fields intentionally mirror
``eval_java.py`` so downstream aggregation can consume both languages with
minimal language-specific handling.
"""

from __future__ import annotations

import argparse
import ast
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
INSTANCE_SCRIPT = EVAL_DIR / "python_eval_container.sh"
MERGE_SCRIPT = EVAL_DIR / "python_merge_coverage.sh"
COVERAGE_CONFIG = EVAL_DIR / "python_coveragerc"


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


def _coverage(total: int, covered: int) -> dict[str, Any]:
    return {
        "total": total,
        "covered": covered,
        "rate": covered / total if total else 0.0,
    }


def _summary_coverage(summary: dict[str, Any]) -> dict[str, Any]:
    line_total = int(summary.get("num_statements", 0) or 0)
    line_covered = int(summary.get("covered_lines", 0) or 0)
    branch_total = int(summary.get("num_branches", 0) or 0)
    branch_covered = int(summary.get("covered_branches", 0) or 0)
    return {
        "line": _coverage(line_total, line_covered),
        "branch": _coverage(branch_total, branch_covered),
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
    report: dict[str, Any], item: dict[str, Any]
) -> tuple[str | None, dict[str, Any] | None]:
    wanted = _source_key(item)
    files = report.get("files") or {}
    normalized = {_normalize_path(str(key)): (str(key), value) for key, value in files.items()}
    if wanted in normalized:
        return normalized[wanted]
    suffix_matches = [
        pair for key, pair in normalized.items() if key.endswith("/" + wanted) or wanted.endswith("/" + key)
    ]
    if len(suffix_matches) == 1:
        return suffix_matches[0]
    return None, None


def _requested_function_name(item: dict[str, Any]) -> str:
    name = str(item.get("name", ""))
    class_name = str(item.get("class_name") or "")
    if name == class_name or str(item.get("type", "")).lower() == "constructor":
        name = "__init__"
    return f"{class_name}.{name}" if class_name else name


def _range_function_coverage(
    file_data: dict[str, Any], item: dict[str, Any]
) -> dict[str, Any] | None:
    start = int(item.get("start_line") or 0)
    end = int(item.get("end_line") or 0)
    if not start or not end or end < start:
        return None

    executed_lines = {int(line) for line in file_data.get("executed_lines", [])}
    missing_lines = {int(line) for line in file_data.get("missing_lines", [])}
    executable = {line for line in executed_lines | missing_lines if start <= line <= end}
    covered_lines = executable & executed_lines

    def branch_set(key: str) -> set[tuple[int, int]]:
        branches: set[tuple[int, int]] = set()
        for value in file_data.get(key, []) or []:
            if isinstance(value, list) and len(value) == 2:
                branch = (int(value[0]), int(value[1]))
                if start <= branch[0] <= end:
                    branches.add(branch)
        return branches

    executed_branches = branch_set("executed_branches")
    missing_branches = branch_set("missing_branches")
    all_branches = executed_branches | missing_branches
    name = _requested_function_name(item)
    return {
        "line": _coverage(len(executable), len(covered_lines)),
        "branch": _coverage(len(all_branches), len(executed_branches)),
        "matched_methods": [
            {
                "class": str(item.get("class_name") or ""),
                "method": name,
                "first_line": start,
                "last_line": end,
                "match_source": "source_range",
            }
        ],
        "ambiguous_match": False,
    }


def _reported_function_coverage(
    file_data: dict[str, Any], item: dict[str, Any]
) -> dict[str, Any] | None:
    functions = file_data.get("functions") or {}
    requested = _requested_function_name(item)
    candidates: list[tuple[str, dict[str, Any]]] = []
    for name, data in functions.items():
        if not name:
            continue
        if name == requested or name.endswith("." + requested):
            candidates.append((name, data))
    if not candidates and "." in requested:
        leaf = requested.rsplit(".", 1)[-1]
        candidates = [
            (name, data)
            for name, data in functions.items()
            if name == leaf or name.endswith("." + leaf)
        ]
    if not candidates:
        return None

    line_total = line_covered = branch_total = branch_covered = 0
    matched: list[dict[str, Any]] = []
    for name, data in candidates:
        summary = data.get("summary") or {}
        pair = _summary_coverage(summary)
        line_total += pair["line"]["total"]
        line_covered += pair["line"]["covered"]
        branch_total += pair["branch"]["total"]
        branch_covered += pair["branch"]["covered"]
        matched.append(
            {
                "class": str(item.get("class_name") or ""),
                "method": name,
                "first_line": int(item.get("start_line") or 0),
                "last_line": int(item.get("end_line") or 0),
                "match_source": "coverage_functions",
            }
        )
    return {
        "line": _coverage(line_total, line_covered),
        "branch": _coverage(branch_total, branch_covered),
        "matched_methods": matched,
        "ambiguous_match": len(matched) != 1,
    }


def parse_instance_coverage(json_path: Path, item: dict[str, Any]) -> dict[str, Any]:
    """Read target function and target source-file coverage from one run."""
    empty = {"report_found": False, "target_file": None, "target_function": None}
    if not json_path.is_file():
        return empty
    try:
        report = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {**empty, "parse_error": str(error)}

    file_key, file_data = _find_file_entry(report, item)
    if file_data is None:
        return {"report_found": True, "target_file": None, "target_function": None}
    target_file = {
        "file_key": _normalize_path(file_key or _source_key(item)),
        **_summary_coverage(file_data.get("summary") or {}),
    }
    target_function = _reported_function_coverage(file_data, item)
    if target_function is None:
        target_function = _range_function_coverage(file_data, item)
    return {
        "report_found": True,
        "target_file": target_file,
        "target_function": target_function,
    }


def parse_pytest_report(report_path: Path) -> dict[str, Any]:
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
    if not report_path.is_file():
        return empty
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        summary = report.get("summary") or {}
        total = int(summary.get("total", summary.get("collected", 0)) or 0)
        failures = int(summary.get("failed", 0) or 0)
        errors = int(summary.get("error", summary.get("errors", 0)) or 0)
        skipped = int(summary.get("skipped", 0) or 0)
        passed = int(summary.get("passed", max(0, total - failures - errors - skipped)) or 0)
        return {
            "total": total,
            "failures": failures,
            "errors": errors,
            "skipped": skipped,
            "passed": passed,
            "pass_rate": passed / total if total else 0.0,
            "report_count": 1,
            "parse_errors": [],
        }
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {**empty, "parse_errors": [str(error)]}


def _stage_item(item: dict[str, Any], stage_dir: Path) -> None:
    test_path = _safe_relative_path(str(item.get("test_file", "")), "test_file")
    src_path = _safe_relative_path(_source_key(item), "src_file")
    generated_tests = item.get("generated_tests") or []
    if isinstance(generated_tests, str):
        generated_tests = [generated_tests]
    code = "\n\n".join(str(part) for part in generated_tests if str(part).strip()).strip()
    if not code:
        raise ValueError("generated_tests is empty")
    _write_text(stage_dir / "files" / Path(*test_path.parts), code + "\n")
    _write_text(stage_dir / "test_file.txt", test_path.as_posix() + "\n")
    _write_text(stage_dir / "src_file.txt", src_path.as_posix() + "\n")

    for config in item.get("generated_config_files") or []:
        if not isinstance(config, dict) or not config.get("path"):
            continue
        config_path = _safe_relative_path(str(config["path"]), "generated_config_files.path")
        _write_text(stage_dir / "files" / Path(*config_path.parts), str(config.get("code", "")))


def analyse_python_syntax(item: dict[str, Any]) -> dict[str, Any]:
    generated_tests = item.get("generated_tests") or []
    if isinstance(generated_tests, str):
        generated_tests = [generated_tests]
    code = "\n\n".join(str(part) for part in generated_tests if str(part).strip()).strip()
    result: dict[str, Any] = {
        "parser": "python-ast",
        "parser_available": True,
        "has_code": bool(code),
        "correct": False,
    }
    if not code:
        result.update(error_type="EmptyGeneratedTest", error_message="generated_tests is empty")
        return result
    try:
        ast.parse(code, filename="<generated_test>", mode="exec")
        result["correct"] = True
    except (SyntaxError, ValueError, TypeError) as error:
        result.update(
            error_type=type(error).__name__,
            error_message=str(error)[:1000],
        )
    return result


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
    keep_logs: bool,
    keep_individual_json: bool,
    install_eval_deps: bool,
) -> dict[str, Any]:
    instance_id = _instance_id(index, item)
    container_suffix = hashlib.sha1(str(output_dir).encode("utf-8")).hexdigest()[:8]
    container_name = f"adverbug-py-eval-{container_suffix}-{instance_id}"[:120]
    started = time.monotonic()
    evaluation: dict[str, Any] = {
        "instance_id": instance_id,
        "compile_pass": False,
        "test_pass": False,
        "failure_stage": None,
    }

    with tempfile.TemporaryDirectory(prefix="python-eval-input-") as stage_name, tempfile.TemporaryDirectory(
        prefix="python-eval-output-"
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
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "-v",
            f"{stage_dir}:/eval-input:ro",
            "-v",
            f"{run_dir}:/results",
            "-v",
            f"{INSTANCE_SCRIPT}:/eval/python_eval_container.sh:ro",
            "-v",
            f"{COVERAGE_CONFIG}:/eval/python_coveragerc:ro",
            "-e",
            f"INSTALL_EVAL_DEPS={1 if install_eval_deps else 0}",
            "-e",
            f"PYTEST_TIMEOUT={test_timeout}",
            image,
            "bash",
            "/eval/python_eval_container.sh",
        ]
        completed: subprocess.CompletedProcess[str] | None
        try:
            completed = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
            evaluation["container_exit_code"] = completed.returncode
        except subprocess.TimeoutExpired as error:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                text=True,
                capture_output=True,
                check=False,
            )
            evaluation.update(failure_stage="timeout", failure_message=f"Exceeded {timeout} seconds")
            completed = None
            captured = (error.stdout or "") + "\n" + (error.stderr or "")
            _write_text(output_dir / "logs" / f"{instance_id}.log", captured)
        except KeyboardInterrupt:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                text=True,
                capture_output=True,
                check=False,
            )
            raise

        compile_exit = _read_int(run_dir / "compile_exit_code.txt")
        test_exit = _read_int(run_dir / "test_exit_code.txt")
        evaluation["compile_exit_code"] = compile_exit
        evaluation["test_exit_code"] = test_exit
        # Pytest exit 5 means collection itself succeeded but found no tests.
        # Keep compilation/collection distinct from the later test-pass metric,
        # matching Java's successful test compilation with zero executed tests.
        evaluation["compile_pass"] = compile_exit in (0, 5)

        test_summary = parse_pytest_report(run_dir / "report.json")
        evaluation["test_summary"] = test_summary
        evaluation["test_pass"] = bool(
            compile_exit in (0, 5)
            and test_exit == 0
            and test_summary["total"] > 0
            and test_summary["passed"] > 0
            and test_summary["failures"] == 0
            and test_summary["errors"] == 0
        )

        if evaluation["failure_stage"] is None:
            if compile_exit is None:
                evaluation["failure_stage"] = "infrastructure"
            elif compile_exit not in (0, 5):
                evaluation["failure_stage"] = "compile"
            elif test_exit is None:
                evaluation["failure_stage"] = "test_infrastructure"
            elif test_exit != 0 or not evaluation["test_pass"]:
                evaluation["failure_stage"] = "test"

        data_destination = output_dir / "exec" / f"{instance_id}.coverage"
        saved_data = _copy_if_present(run_dir / ".coverage", data_destination)
        evaluation["coverage_data"] = (
            str(data_destination.relative_to(output_dir)) if saved_data else None
        )
        evaluation["coverage"] = parse_instance_coverage(run_dir / "coverage.json", item)

        instance_json = run_dir / "coverage.json"
        if keep_individual_json and instance_json.is_file():
            json_destination = output_dir / "individual_json" / f"{instance_id}.json"
            _copy_if_present(instance_json, json_destination)
            evaluation["coverage_json"] = str(json_destination.relative_to(output_dir))

        should_keep_log = (
            keep_logs
            or not evaluation["compile_pass"]
            or not evaluation["test_pass"]
            or not evaluation["coverage_data"]
        )
        if should_keep_log:
            log_parts: list[str] = []
            if completed is not None:
                log_parts.extend(
                    [
                        "=== docker stdout ===\n" + completed.stdout,
                        "=== docker stderr ===\n" + completed.stderr,
                    ]
                )
            for name in ("dependencies.log", "compile.log", "test.log", "coverage.log"):
                log_path = run_dir / name
                if log_path.is_file():
                    log_parts.append(
                        f"=== {name} ===\n"
                        + log_path.read_text(encoding="utf-8", errors="replace")
                    )
            destination = output_dir / "logs" / f"{instance_id}.log"
            _write_text(destination, "\n".join(log_parts))
            evaluation["log"] = str(destination.relative_to(output_dir))

    evaluation["duration_seconds"] = time.monotonic() - started
    return evaluation


def _write_merge_manifests(
    output_dir: Path,
    results: list[dict[str, Any]],
    kind: str,
) -> tuple[list[str], set[str]]:
    data_paths: list[str] = []
    files: set[str] = set()
    file_group_lines: list[str] = []
    for item in results:
        evaluation = item.get("evaluation") or {}
        include = evaluation.get("coverage_data") and (
            kind == "all_executed" or evaluation.get("test_pass") is True
        )
        src_file = _source_key(item)
        if include:
            data_path = str(evaluation["coverage_data"])
            data_paths.append(data_path)
            if src_file:
                files.add(src_file)
                file_group_lines.append(
                    "\t".join((_file_slug(src_file), src_file, data_path))
                )
        elif src_file:
            files.add(src_file)

    _write_text(
        output_dir / f"{kind}_exec_manifest.txt",
        "\n".join(data_paths) + ("\n" if data_paths else ""),
    )
    _write_text(
        output_dir / f"{kind}_file_groups.tsv",
        "\n".join(file_group_lines) + ("\n" if file_group_lines else ""),
    )
    return data_paths, files


def merge_coverage(
    *,
    image: str,
    output_dir: Path,
    results: list[dict[str, Any]],
    kind: str,
    timeout: int,
    install_eval_deps: bool,
) -> dict[str, Any]:
    data_paths, files = _write_merge_manifests(output_dir, results, kind)
    status: dict[str, Any] = {
        "kind": kind,
        "exec_count": len(data_paths),
        "success": False,
        "modules": {".": "root"} if files else {},
        "file_group_count": len(
            {
                _source_key(item)
                for item in results
                if _source_key(item)
                and (item.get("evaluation") or {}).get("coverage_data")
                and (
                    kind == "all_executed"
                    or (item.get("evaluation") or {}).get("test_pass") is True
                )
            }
        ),
    }
    if not data_paths:
        status["error"] = "No coverage.py data files were eligible for merging"
        return status

    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{output_dir}:/results",
        "-v",
        f"{MERGE_SCRIPT}:/eval/python_merge_coverage.sh:ro",
        "-v",
        f"{COVERAGE_CONFIG}:/eval/python_coveragerc:ro",
        "-e",
        f"COVERAGE_KIND={kind}",
        "-e",
        f"INSTALL_EVAL_DEPS={1 if install_eval_deps else 0}",
        image,
        "bash",
        "/eval/python_merge_coverage.sh",
    ]
    try:
        completed = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
        status["container_exit_code"] = completed.returncode
        status["success"] = completed.returncode == 0
        if completed.returncode != 0:
            status["error"] = (completed.stderr or completed.stdout)[-4000:]
        _write_text(
            output_dir / "coverage" / kind / "merge.log",
            "=== stdout ===\n" + completed.stdout + "\n=== stderr ===\n" + completed.stderr,
        )
    except subprocess.TimeoutExpired:
        status["error"] = f"Coverage merge exceeded {timeout} seconds"
    return status


def collect_merged_file_coverage(
    output_dir: Path,
    results: list[dict[str, Any]],
    kind: str,
) -> dict[str, Any]:
    wanted_files = sorted(
        {_source_key(item) for item in results if item.get("evaluation") and _source_key(item)}
    )
    collected: dict[str, Any] = {}
    for src_file in wanted_files:
        json_path = output_dir / "coverage" / kind / "files" / f"{_file_slug(src_file)}.json"
        base = {"module": ".", "file_key": src_file}
        if not json_path.is_file():
            collected[src_file] = {"report_found": False, **base}
            continue
        try:
            report = json.loads(json_path.read_text(encoding="utf-8"))
            _, file_data = _find_file_entry(report, {"src_file": src_file})
        except (OSError, json.JSONDecodeError) as error:
            collected[src_file] = {"report_found": False, **base, "parse_error": str(error)}
            continue
        if file_data is None:
            collected[src_file] = {"report_found": False, **base}
        else:
            collected[src_file] = {
                "report_found": True,
                **base,
                **_summary_coverage(file_data.get("summary") or {}),
            }
    return collected


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
        if isinstance(previous, list) and len(previous) == len(source_items):
            results = []
            for source_item, previous_item in zip(source_items, previous):
                refreshed = dict(source_item)
                if "evaluation" in previous_item:
                    refreshed["evaluation"] = previous_item["evaluation"]
                results.append(refreshed)
        else:
            raise ValueError("Cannot resume: evaluated_results.json does not match input length")
    else:
        results = source_items

    for item in results:
        item["syntax_evaluation"] = analyse_python_syntax(item)
    _atomic_json_dump(evaluated_path, results)

    stop = len(results) if args.limit is None else min(len(results), args.start + args.limit)
    pending: list[int] = []
    for index in range(args.start, stop):
        item = results[index]
        existing = item.get("evaluation") or {}
        existing_data = existing.get("coverage_data")
        if args.resume and not args.redo_existing and existing.get("compile_exit_code") is not None:
            finished_without_coverage = existing.get("compile_pass") is False
            finished_with_coverage = bool(
                existing_data and (output_dir / str(existing_data)).is_file()
            )
            if finished_without_coverage or finished_with_coverage:
                print(f"[{index + 1}/{len(results)}] resume: {item.get('name')}", flush=True)
                continue
        pending.append(index)

    def run_index(index: int) -> tuple[int, dict[str, Any]]:
        item = results[index]
        print(
            f"[{index + 1}/{len(results)}] evaluating {item.get('name')} in a fresh container",
            flush=True,
        )
        return index, evaluate_instance(
            image=args.image,
            item=item,
            index=index,
            output_dir=output_dir,
            timeout=args.timeout,
            test_timeout=args.test_timeout,
            keep_logs=args.keep_logs,
            keep_individual_json=args.keep_individual_json,
            install_eval_deps=not args.no_install_eval_deps,
        )

    if args.workers == 1:
        for index in pending:
            completed_index, evaluation = run_index(index)
            results[completed_index]["evaluation"] = evaluation
            _atomic_json_dump(evaluated_path, results)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(run_index, index) for index in pending]
            for future in concurrent.futures.as_completed(futures):
                index, evaluation = future.result()
                results[index]["evaluation"] = evaluation
                _atomic_json_dump(evaluated_path, results)

    merge_summaries: dict[str, Any] = {}
    file_coverage: dict[str, Any] = {}
    if not args.no_merge:
        for kind in ("all_executed", "passing"):
            status = merge_coverage(
                image=args.image,
                output_dir=output_dir,
                results=results,
                kind=kind,
                timeout=args.merge_timeout,
                install_eval_deps=not args.no_install_eval_deps,
            )
            merge_summaries[kind] = status
            file_coverage[kind] = collect_merged_file_coverage(output_dir, results, kind)

    evaluated = [item.get("evaluation") or {} for item in results if item.get("evaluation")]
    syntax_results = [item["syntax_evaluation"] for item in results]
    syntax_correct = sum(entry.get("correct") is True for entry in syntax_results)
    summary = {
        "input": str(data_file),
        "image": args.image,
        "target_count": len(source_items),
        "evaluated_count": len(evaluated),
        "compile_pass_count": sum(entry.get("compile_pass") is True for entry in evaluated),
        "test_pass_count": sum(entry.get("test_pass") is True for entry in evaluated),
        "exec_count": sum(bool(entry.get("coverage_data")) for entry in evaluated),
        "syntax": {
            "parser": "python-ast",
            "parser_available": True,
            "total": len(syntax_results),
            "correct": syntax_correct,
            "incorrect": len(syntax_results) - syntax_correct,
            "correct_rate": syntax_correct / len(syntax_results) if syntax_results else 0.0,
        },
        "merge": merge_summaries,
    }
    _atomic_json_dump(evaluated_path, results)
    _atomic_json_dump(output_dir / "file_coverage.json", file_coverage)
    _atomic_json_dump(output_dir / "summary.json", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate each generated Python test in a fresh container and merge coverage.py data."
    )
    parser.add_argument("--data-file", type=Path, required=True, help="Generated-test JSON")
    parser.add_argument("--image", help="Prebuilt project image")
    parser.add_argument("--dockerfile", type=Path, help="Build an image from this Dockerfile first")
    parser.add_argument("--build-context", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=1200, help="Seconds per function")
    parser.add_argument(
        "--test-timeout",
        type=int,
        default=60,
        help="Seconds allowed for each individual pytest test case",
    )
    parser.add_argument("--merge-timeout", type=int, default=1800)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--redo-existing",
        action="store_true",
        help="With --resume, force reevaluation of entries selected by --start/--limit",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of independently isolated function containers to evaluate concurrently",
    )
    parser.add_argument("--no-merge", action="store_true")
    parser.add_argument("--keep-logs", action="store_true")
    parser.add_argument("--keep-individual-json", action="store_true")
    parser.add_argument(
        "--no-install-eval-deps",
        action="store_true",
        help="Require pytest/coverage plugins to already exist in the image",
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
        or args.merge_timeout < 1
    ):
        parser.error(
            "--start must be non-negative; --limit, --workers, and timeouts must be positive"
        )
    if not args.image:
        args.image = f"adverbug-python-eval-{_safe_name(args.data_file.stem)}:latest"
    if args.dockerfile:
        _build_image(args.dockerfile.resolve(), args.build_context.resolve(), args.image)
    summary = evaluate_dataset(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
