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
from collections import Counter, defaultdict
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
FunctionKey = tuple[str, str, int]  # relative source path, qualname, first line


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
        _write(["D", relative.replace("\\", "/"), frame.f_code.co_qualname,
                frame.f_code.co_name, str(frame.f_code.co_firstlineno)])
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


def _functions_in_tree(tree: ast.AST, relative_path: str) -> list[tuple[ast.AST, FunctionKey, bool]]:
    """Return project functions with a coverage-compatible qualified identity."""
    functions: list[tuple[ast.AST, FunctionKey, bool]] = []

    def walk(body: list[ast.stmt], prefix: str = "") -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                walk(node.body, prefix + node.name + ".")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                is_property = any(
                    (isinstance(decorator, ast.Name)
                     and decorator.id in {"property", "cached_property"})
                    or (isinstance(decorator, ast.Attribute)
                        and decorator.attr in {"getter", "cached_property"})
                    for decorator in node.decorator_list
                )
                functions.append((node, (relative_path, prefix + node.name, node.lineno), is_property))
                # Nested functions are separately identifiable at runtime but
                # are not traversed as part of the enclosing function's body.
                walk(node.body, prefix + node.name + ".<locals>.")

    if isinstance(tree, ast.Module):
        walk(tree.body)
    return functions


@lru_cache(maxsize=None)
def _project_symbols(
    root: Path,
) -> tuple[
    set[FunctionKey],
    dict[str, set[FunctionKey]],
    dict[tuple[str, str], set[FunctionKey]],
    dict[tuple[str, str], set[FunctionKey]],
]:
    """Index production functions by exact location and conservative aliases."""
    all_functions: set[FunctionKey] = set()
    by_name: dict[str, set[FunctionKey]] = defaultdict(set)
    by_file_name: dict[tuple[str, str], set[FunctionKey]] = defaultdict(set)
    by_module_name: dict[tuple[str, str], set[FunctionKey]] = defaultdict(set)
    for path in root.rglob("*.py"):
        if not _is_production_python(path, root):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError):
            continue
        relative = path.relative_to(root).as_posix()
        module = ".".join(path.relative_to(root).with_suffix("").parts)
        for _, key, _ in _functions_in_tree(tree, relative):
            all_functions.add(key)
            bare_name = key[1].rsplit(".", 1)[-1]
            by_name[bare_name].add(key)
            by_file_name[(relative, bare_name)].add(key)
            by_module_name[(module, bare_name)].add(key)
    return all_functions, dict(by_name), dict(by_file_name), dict(by_module_name)


def _static_candidates(item: dict[str, Any]) -> set[FunctionKey]:
    path = _source_path(item)
    if not path.is_file():
        return set()
    root = Path(str(item.get("project_root") or ".")).resolve()
    _, by_name, by_file_name, by_module_name = _project_symbols(root)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    relative = path.relative_to(root).as_posix()
    start = int(item.get("start_line") or 0)
    end = int(item.get("end_line") or 0)
    target_name = str(item.get("name") or "")
    functions = _functions_in_tree(tree, relative)
    targets = [(node, key) for node, key, _ in functions
               if key[1].rsplit(".", 1)[-1] == target_name
               and (not start or key[2] == start)]
    if not targets:
        targets = [(node, key) for node, key, _ in functions
                   if key[1].rsplit(".", 1)[-1] == target_name]
    if not targets:
        return set()
    target, target_key = targets[0]
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
    calls: set[FunctionKey] = set()

    def unique(candidates: set[FunctionKey] | None) -> None:
        # Do not turn an unresolved name into every same-named function in the
        # repository. Dynamic tracing can still add it to D if it executes.
        if candidates and len(candidates) == 1:
            calls.update(candidates)

    class DirectCallVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            if node is target:
                self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            if node is target:
                self.generic_visit(node)

        def visit_Lambda(self, node: ast.Lambda) -> None:
            # A lambda body is not evaluated until later; it is not a direct
            # call made by the enclosing target function.
            return

        def visit_Call(self, call: ast.Call) -> None:
            function = call.func
            if isinstance(function, ast.Name):
                imported = imported_symbols.get(function.id)
                if imported:
                    unique(by_module_name.get(imported))
                else:
                    local = by_file_name.get((relative, function.id), set())
                    unique(local if local else by_name.get(function.id))
            elif isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name):
                owner = function.value.id
                if owner in {"self", "cls"}:
                    class_prefix = target_key[1].rsplit(".", 1)[0]
                    unique({key for key in by_file_name.get((relative, function.attr), set())
                            if key[1] == class_prefix + "." + function.attr})
                else:
                    module = module_aliases.get(owner)
                    if module:
                        unique(by_module_name.get((module, function.attr)))
            self.generic_visit(call)

        def visit_Attribute(self, attribute: ast.Attribute) -> None:
            # Python properties invoke a project function without ast.Call.
            if isinstance(attribute.value, ast.Name) and attribute.value.id in {"self", "cls"}:
                class_prefix = target_key[1].rsplit(".", 1)[0]
                unique({key for key in by_file_name.get((relative, attribute.attr), set())
                        if key[1] == class_prefix + "." + attribute.attr})
            self.generic_visit(attribute)

    DirectCallVisitor().visit(target)
    return calls


def _dynamic_candidates(path: Path) -> Counter[FunctionKey]:
    counts: Counter[FunctionKey] = Counter()
    if not path.is_file():
        return counts
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = raw.split("\t")
        if len(parts) == 5 and parts[0] == "D":
            try:
                counts[(parts[1], parts[2], int(parts[4]))] += 1
            except ValueError:
                continue
    return counts


def _coverage_for_candidates(path: Path, candidates: set[FunctionKey]) -> dict[str, Any]:
    """Aggregate function line/branch coverage for the S union D candidates."""
    result = {"line": {"covered": 0, "total": 0, "rate": None},
              "branch": {"covered": 0, "total": 0, "rate": None},
              "matched_function_count": 0, "unmatched_function_count": len(candidates)}
    if not candidates or not path.is_file():
        return result
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return result
    seen: set[FunctionKey] = set()
    for file_name, file_data in (report.get("files") or {}).items():
        normalized_file = str(file_name).replace("\\", "/").removeprefix("./")
        for function_name, data in (file_data.get("functions") or {}).items():
            key = (normalized_file, function_name, int(data.get("start_line", 0) or 0))
            if key not in candidates:
                continue
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
    result["unmatched_function_count"] = len(candidates - seen)
    for kind in ("line", "branch"):
        total = result[kind]["total"]
        result[kind]["rate"] = result[kind]["covered"] / total if total else None
    return result


def _format_function_key(key: FunctionKey) -> dict[str, Any]:
    return {"file": key[0], "qualname": key[1], "first_line": key[2]}


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
        "static_called_functions": [_format_function_key(key) for key in sorted(static)],
        "executed_called_functions": [
            {**_format_function_key(key), "call_count": dynamic_counts[key]}
            for key in sorted(dynamic)
        ],
        "called_function_coverage": {
            "candidate_scope": "static_union_dynamic_project_production_functions",
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
            "unmatched_function_count": called_coverage["unmatched_function_count"],
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
