#!/usr/bin/env python3
"""Function-level Python called-function coverage prototype.

The script reuses the existing isolated Python evaluation container.  A
``sitecustomize`` module installs ``sys.setprofile`` and records direct calls
whose caller is the benchmark target function.  Both static and dynamic
candidates are restricted to functions implemented in the project's
production Python files.  The reported metric is
``|dynamic| / |static union dynamic|``.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import tempfile
import textwrap
import time
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    from eval_py import _safe_relative_path, _stage_item
except ModuleNotFoundError:  # package-style imports used by checks and notebooks
    from .eval_py import _safe_relative_path, _stage_item


EVAL_DIR = Path(__file__).resolve().parent
INSTANCE_SCRIPT = EVAL_DIR / "python_eval_container.sh"
TRACE_INSTANCE_SCRIPT = EVAL_DIR / "python_dynamic_calls_container.sh"


PROFILE_SOURCE = r'''
import json
import os
import sys
import threading

_target_file = os.environ.get("ADVER_TRACE_TARGET_FILE", "")
_target_name = os.environ.get("ADVER_TRACE_TARGET_NAME", "")
_output = os.environ.get("ADVER_TRACE_OUTPUT", "")
_test_file = os.path.abspath(os.environ.get("ADVER_TRACE_TEST_FILE", ""))
_lock = threading.Lock()

def _write(parts):
    if not _output:
        return
    try:
        with _lock, open(_output, "a", encoding="utf-8") as handle:
            handle.write("\t".join(parts) + "\n")
    except OSError:
        pass

def _profile(frame, event, arg):
    if event != "call":
        return _profile
    caller = frame.f_back
    if caller is None:
        return _profile
    caller_file = os.path.abspath(caller.f_code.co_filename)
    if caller_file != _target_file or caller.f_code.co_name != _target_name:
        return _profile
    callee_file = os.path.abspath(frame.f_code.co_filename)
    # Only count functions implemented by the checked-out project.  In
    # particular, do not count generated-test helpers/replacements such as a
    # monkeypatched lambda.  Calls into the standard library and site-packages
    # are outside cwd and are excluded by the first condition.
    relative = os.path.relpath(callee_file, os.path.abspath(os.getcwd()))
    parts = relative.replace("\\", "/").split("/")
    is_test_code = any(part == "tests" or part == "test" or part.startswith("test_")
                       for part in parts)
    if (callee_file.startswith(os.path.abspath(os.getcwd()) + os.sep)
            and callee_file != _test_file and not is_test_code):
        _write(["D", callee_file, frame.f_code.co_qualname, frame.f_code.co_name])
    return _profile

def enable():
    sys.setprofile(_profile)
    threading.setprofile(_profile)

if os.environ.get("ADVER_TRACE_DISABLED") != "1":
    enable()

'''


def _instance_id(index: int, item: dict[str, Any]) -> str:
    identity = "|".join(str(item.get(k, "")) for k in ("src_file", "name", "start_line"))
    digest = hashlib.sha1(identity.encode()).hexdigest()[:10]
    return f"{index:04d}_{str(item.get('name', 'function'))[:35]}_{digest}"


def _source_path(item: dict[str, Any]) -> Path:
    root = Path(str(item.get("project_root") or "."))
    return root / _safe_relative_path(str(item.get("src_file", "")), "src_file")


def _is_production_python(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return False
    return path.suffix == ".py" and not any(
        part in {"test", "tests"} or part.startswith("test_") for part in parts
    )


@lru_cache(maxsize=None)
def _project_symbols(
    root: Path,
) -> tuple[set[str], dict[str, set[str]], set[str]]:
    """Return function and property names in production project modules."""
    names: set[str] = set()
    by_module: dict[str, set[str]] = {}
    properties: set[str] = set()
    for path in root.rglob("*.py"):
        if not _is_production_python(path, root):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError):
            continue
        module = ".".join(path.relative_to(root).with_suffix("").parts)
        module_names = {
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if ((isinstance(decorator, ast.Name)
                     and decorator.id in {"property", "cached_property"})
                        or (isinstance(decorator, ast.Attribute)
                            and decorator.attr in {"getter", "cached_property"})):
                    properties.add(node.name)
                    break
        names.update(module_names)
        by_module[module] = module_names
    return names, by_module, properties


def _static_candidates(item: dict[str, Any]) -> set[str]:
    path = _source_path(item)
    if not path.is_file():
        return set()
    root = Path(str(item.get("project_root") or ".")).resolve()
    project_names, module_symbols, project_properties = _project_symbols(root)
    project_packages = {module.split(".", 1)[0] for module in module_symbols}
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    start = int(item.get("start_line") or 0)
    end = int(item.get("end_line") or 0)
    target_name = str(item.get("name") or "")
    nodes = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == target_name
        and (not start or getattr(node, "lineno", 0) == start)
    ]
    if not nodes:
        nodes = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == target_name]
    if not nodes:
        return set()
    # Resolve imported names well enough to distinguish project helpers from
    # numpy/matplotlib/stdlib calls.  Attribute calls are accepted only for a
    # project module alias or a direct self/cls method call; chained values such
    # as ``dataframe.copy()`` are intentionally not guessed by name.
    imported_symbols: dict[str, tuple[str, str]] = {}
    module_aliases: dict[str, str] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                module_aliases[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(statement, ast.ImportFrom) and statement.module:
            for alias in statement.names:
                imported_symbols[alias.asname or alias.name] = (statement.module, alias.name)
    calls: set[str] = set()
    for call in ast.walk(nodes[0]):
        if not isinstance(call, ast.Call):
            continue
        function = call.func
        if isinstance(function, ast.Name):
            imported = imported_symbols.get(function.id)
            if imported:
                module, symbol = imported
                # A package __init__ commonly re-exports a function defined in
                # one of its private submodules, so exact-module lookup alone
                # is too strict here.
                if (module.split(".", 1)[0] in project_packages
                        and symbol in project_names):
                    calls.add(symbol)
            elif function.id in project_names:
                calls.add(function.id)
        elif isinstance(function, ast.Attribute):
            if isinstance(function.value, ast.Name):
                owner = function.value.id
                if owner in {"self", "cls"} and function.attr in project_names:
                    calls.add(function.attr)
                else:
                    module = module_aliases.get(owner)
                    if (module and module.split(".", 1)[0] in project_packages
                            and function.attr in project_names):
                        calls.add(function.attr)
    # A property getter is invoked by attribute access rather than ast.Call.
    # Keeping it in the static set ensures that monkeypatching the property
    # does not make the original project getter disappear from the denominator.
    for attribute in ast.walk(nodes[0]):
        if (isinstance(attribute, ast.Attribute)
                and isinstance(attribute.value, ast.Name)
                and attribute.value.id in {"self", "cls"}
                and attribute.attr in project_properties):
            calls.add(attribute.attr)
    return calls


def _dynamic_candidates(path: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not path.is_file():
        return counts
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = raw.split("\t", 3)
        if len(parts) == 4 and parts[0] == "D":
            qualified = parts[2]
            # AST calls use the source-level spelling (e.g. ``Arsenal`` or
            # ``fit``), while profiling reports Python qualnames
            # (e.g. ``Arsenal.__init__`` or ``Estimator.fit``).
            if qualified.endswith(".__init__"):
                canonical = qualified.rsplit(".", 1)[0]
            elif "." in qualified:
                canonical = qualified.rsplit(".", 1)[-1]
            else:
                canonical = qualified
            counts[canonical] += 1
    return counts


def _coverage_for_candidates(path: Path, candidates: set[str]) -> dict[str, Any]:
    """Aggregate function line/branch coverage for the S union D candidates."""
    result = {"line": {"covered": 0, "total": 0, "rate": None},
              "branch": {"covered": 0, "total": 0, "rate": None},
              "matched_function_count": 0}
    if not candidates or not path.is_file():
        return result
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return result
    seen: set[tuple[str, str]] = set()
    for file_name, file_data in (report.get("files") or {}).items():
        for function_name, data in (file_data.get("functions") or {}).items():
            canonical = function_name.rsplit(".", 1)[-1]
            if function_name.endswith(".__init__"):
                canonical = function_name.rsplit(".", 1)[0]
            if canonical not in candidates and function_name not in candidates:
                continue
            key = (str(file_name), function_name)
            if key in seen:
                continue
            seen.add(key)
            summary = data.get("summary") or {}
            line_total = int(summary.get("num_statements", 0) or 0)
            line_covered = int(summary.get("covered_lines", 0) or 0)
            branch_total = int(summary.get("num_branches", 0) or 0)
            branch_covered = int(summary.get("covered_branches", 0) or 0)
            result["line"]["total"] += line_total
            result["line"]["covered"] += line_covered
            result["branch"]["total"] += branch_total
            result["branch"]["covered"] += branch_covered
            result["matched_function_count"] += 1
    for kind in ("line", "branch"):
        total = result[kind]["total"]
        result[kind]["rate"] = result[kind]["covered"] / total if total else None
    return result


def _evaluate_one(item: dict[str, Any], index: int, image: str, output_dir: Path,
                  timeout: int, pytest_cov_wheel_dir: Path | None) -> dict[str, Any]:
    instance_id = _instance_id(index, item)
    run_dir = output_dir / "runs" / instance_id
    run_dir.mkdir(parents=True, exist_ok=True)
    static = _static_candidates(item)
    with tempfile.TemporaryDirectory(prefix="python-trace-input-") as stage_name, tempfile.TemporaryDirectory(prefix="python-trace-modules-") as trace_name:
        stage = Path(stage_name)
        trace = Path(trace_name)
        _stage_item(item, stage)
        (trace / "sitecustomize.py").write_text(PROFILE_SOURCE, encoding="utf-8")
        (trace / "adver_trace_plugin.py").write_text(
            "import sitecustomize\n\n"
            "def pytest_sessionstart(session):\n"
            "    if sitecustomize.os.environ.get('ADVER_TRACE_DISABLED') != '1':\n"
            "        sitecustomize.enable()\n",
            encoding="utf-8",
        )
        target_file = "/testbed/" + str(item["src_file"]).replace("\\", "/")
        test_file = _safe_relative_path(
            str(item.get("test_file", "")), "test_file"
        ).as_posix()
        command = [
            "docker", "run", "--rm", "--name", "adverbug-python-trace-" + instance_id,
            "-v", f"{stage}:/eval-input:ro", "-v", f"{run_dir}:/results",
            "-v", f"{trace}:/trace:ro",
            "-v", f"{INSTANCE_SCRIPT}:/eval/python_eval_container.sh:ro",
            "-v", f"{TRACE_INSTANCE_SCRIPT}:/eval/python_dynamic_calls_container.sh:ro",
            "-v", f"{EVAL_DIR / 'python_coveragerc'}:/eval/python_coveragerc:ro",
            "-e", "INSTALL_EVAL_DEPS=1",
            "-e", "PYTHONPATH=/trace",
            "-e", "PYTEST_ADDOPTS=-p adver_trace_plugin",
            "-e", f"ADVER_TRACE_TARGET_FILE={target_file}",
            "-e", f"ADVER_TRACE_TARGET_NAME={item.get('name', '')}",
            "-e", f"ADVER_TRACE_TEST_FILE=/testbed/{test_file}",
            "-e", "ADVER_TRACE_OUTPUT=/results/calls.tsv",
        ]
        if pytest_cov_wheel_dir is not None:
            command.extend(["-v", f"{pytest_cov_wheel_dir}:/eval-wheels:ro"])
        command.extend([image, "bash", "/eval/python_dynamic_calls_container.sh"])
        started = time.monotonic()
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
            status = {"container_exit_code": completed.returncode}
            (run_dir / "docker.stdout.log").write_text(completed.stdout, encoding="utf-8")
            (run_dir / "docker.stderr.log").write_text(completed.stderr, encoding="utf-8")
        except subprocess.TimeoutExpired as error:
            subprocess.run(["docker", "rm", "-f", "adverbug-python-trace-" + instance_id], capture_output=True)
            status = {"container_exit_code": None, "timeout": True, "error": str(error)}
    dynamic_counts = _dynamic_candidates(run_dir / "calls.tsv")
    dynamic = set(dynamic_counts)
    candidates = static | dynamic
    called_coverage = _coverage_for_candidates(run_dir / "coverage_all.json", candidates)
    return {
        "instance_id": instance_id,
        "src_file": item.get("src_file"),
        "target_function": item.get("name"),
        "compile_pass": (run_dir / "compile_exit_code.txt").read_text().strip() in ("0", "5") if (run_dir / "compile_exit_code.txt").is_file() else False,
        "test_pass": (run_dir / "test_exit_code.txt").read_text().strip() == "0" if (run_dir / "test_exit_code.txt").is_file() else False,
        "static_called_functions": sorted(static),
        "executed_called_functions": [{"function": key, "call_count": dynamic_counts[key]} for key in sorted(dynamic)],
        "called_function_coverage": {
            "candidate_scope": "project_production_functions",
            "static_called_function_count": len(static),
            "executed_called_function_count": len(dynamic),
            "executed_called_functions_all_phases": len(dynamic),
            "candidate_called_function_count": len(candidates),
            "covered_candidate_count": len(dynamic),
            "coverage_rate": len(dynamic) / len(candidates) if candidates else None,
            "coverage_status": "measured" if candidates else "no_called_functions",
            "static_only_count": len(static - dynamic),
            "dynamic_only_count": len(dynamic - static),
            "line": called_coverage["line"],
            "branch": called_coverage["branch"],
            "matched_function_count": called_coverage["matched_function_count"],
        },
        "duration_seconds": time.monotonic() - started,
        **status,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-file", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--pytest-cov-wheel-dir", type=Path)
    args = parser.parse_args()
    args.data_file = args.data_file.resolve()
    args.output_dir = args.output_dir.resolve()
    if args.pytest_cov_wheel_dir is not None:
        args.pytest_cov_wheel_dir = args.pytest_cov_wheel_dir.resolve()
    items = json.loads(args.data_file.read_text(encoding="utf-8"))
    selected = items[args.start:args.start + args.limit if args.limit is not None else None]
    selected = [item for item in selected if str(item.get("target_type") or "").lower() != "source_file"]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for index, item in enumerate(selected, start=args.start):
        results.append(_evaluate_one(item, index, args.image, args.output_dir, args.timeout,
                                     args.pytest_cov_wheel_dir))
        print(f"[{len(results)}/{len(selected)}] {item.get('name')}", flush=True)
    output = args.output_dir / "dynamic_call_results.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"target_count": len(results), "output": str(output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
