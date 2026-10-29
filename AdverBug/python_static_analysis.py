"""Static Python function metrics and source-to-test matching.

This module deliberately never imports or executes the analyzed project.  It
uses ``ast`` for calls, imports, test discovery, and matching, and optionally
uses lizard for the same NLOC/cyclomatic metrics used by the benchmark
extractor.
"""

import argparse
import ast
import csv
import json
import os
import re
from collections import defaultdict
from pathlib import Path

try:
    import lizard
except ImportError:  # pragma: no cover - the fallback is tested instead
    lizard = None


EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "env",
    "build", "dist", "vendor", "generated", "docs", "doc", "examples",
    "example", "samples", "benchmarks", "scripts", "test", "tests",
    "testing",
}
TEST_DIRS = {"test", "tests", "testing"}
SOURCE_SUFFIX = ".py"


def posix(path):
    return str(path).replace(os.sep, "/")


def is_test_path(rel_path):
    parts = posix(rel_path).split("/")
    lowered = [part.lower() for part in parts]
    base = lowered[-1]
    return (
        any(part in TEST_DIRS for part in lowered[:-1])
        or (base.startswith("test_") and base.endswith(".py"))
        or base.endswith("_test.py")
        or base == "conftest.py"
    )


def is_source_path(rel_path):
    parts = posix(rel_path).split("/")
    lowered = [part.lower() for part in parts]
    base = lowered[-1]
    if not base.endswith(SOURCE_SUFFIX) or base in {"setup.py", "conftest.py"}:
        return False
    if any(part in EXCLUDED_DIRS for part in lowered[:-1]):
        return False
    return not (base.startswith("test_") or base.endswith("_test.py"))


def module_name(rel_path):
    path = posix(rel_path)
    if path.endswith("/__init__.py"):
        path = path[:-12]
    elif path.endswith(".py"):
        path = path[:-3]
    return path.strip("/").replace("/", ".")


def relative_import(module, level, imported):
    if not level:
        return imported
    parts = module.split(".") if module else []
    # A module is below its containing package; an __init__ module is already
    # the package name (both cases are represented by module_name()).
    base = parts[:-1]
    if level > 1:
        base = base[: max(0, len(base) - (level - 1))]
    return ".".join([part for part in base + ([imported] if imported else []) if part])


def dotted_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return dotted_name(node.func)
    if isinstance(node, ast.Subscript):
        return dotted_name(node.value)
    return None


def source_segment(source, node):
    return ast.get_source_segment(source, node) or dotted_name(node) or ast.dump(node, annotate_fields=False)


def function_complexity(node):
    """Fallback McCabe complexity, including the function's own scope only."""
    complexity = 1
    class Complexity(ast.NodeVisitor):
        def visit_If(self, n):
            nonlocal complexity
            complexity += 1
            self.generic_visit(n)

        def visit_For(self, n):
            nonlocal complexity
            complexity += 1
            self.generic_visit(n)

        visit_AsyncFor = visit_For

        def visit_While(self, n):
            nonlocal complexity
            complexity += 1
            self.generic_visit(n)

        def visit_ExceptHandler(self, n):
            nonlocal complexity
            complexity += 1
            self.generic_visit(n)

        def visit_With(self, n):
            nonlocal complexity
            complexity += sum(1 for _ in n.items)
            self.generic_visit(n)

        visit_AsyncWith = visit_With

        def visit_BoolOp(self, n):
            nonlocal complexity
            complexity += max(0, len(n.values) - 1)
            self.generic_visit(n)

        def visit_IfExp(self, n):
            nonlocal complexity
            complexity += 1
            self.generic_visit(n)

        def visit_comprehension(self, n):
            nonlocal complexity
            complexity += 1 + len(n.ifs)
            self.generic_visit(n)

        def visit_FunctionDef(self, n):
            return

        def visit_AsyncFunctionDef(self, n):
            return

        def visit_Lambda(self, n):
            return

        def visit_ClassDef(self, n):
            return

    visitor = Complexity()
    for statement in node.body:
        visitor.visit(statement)
    return complexity


def function_nloc(source, node):
    start = node.lineno
    end = getattr(node, "end_lineno", start)
    lines = source.splitlines()[start - 1:end]
    return sum(1 for line in lines if line.strip() and not line.lstrip().startswith("#"))


def lizard_metrics(source, node):
    fallback = (function_complexity(node), function_nloc(source, node))
    if lizard is None:
        return fallback
    try:
        start = node.lineno - 1
        end = getattr(node, "end_lineno", node.lineno)
        snippet = "\n".join(source.splitlines()[start:end])
        report = lizard.analyze_file.analyze_source_code("static.py", snippet)
        funcs = report.function_list
        if funcs:
            info = funcs[0]
            data = info.__dict__
            return int(data.get("cyclomatic_complexity", fallback[0])), int(data.get("nloc", fallback[1]))
    except Exception:
        pass
    return fallback


class ScopedCallVisitor(ast.NodeVisitor):
    """Collect calls in one function without entering nested scopes."""

    def __init__(self, source, bindings=None, current_class=None):
        self.source = source
        self.bindings = bindings or {}
        self.current_class = current_class
        self.calls = []

    def visit_Call(self, node):
        raw = dotted_name(node.func) or source_segment(self.source, node.func)
        resolved = resolve_binding(raw, self.bindings)
        self.calls.append({
            "raw": raw,
            "normalized": resolved or raw,
            "line": node.lineno,
        })
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        return

    def visit_AsyncFunctionDef(self, node):
        return

    def visit_Lambda(self, node):
        return

    def visit_ClassDef(self, node):
        return


def resolve_binding(name, bindings):
    if not name:
        return None
    first, *rest = name.split(".")
    target = bindings.get(first)
    if target is None:
        return name
    return ".".join([target] + rest)


def import_bindings(tree, module):
    bindings = {}
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                target = alias.name if alias.asname else alias.name.split(".")[0]
                bindings[local] = target
                imports.append({"module": alias.name, "name": None, "alias": local, "line": node.lineno})
        elif isinstance(node, ast.ImportFrom):
            base = relative_import(module, node.level, node.module or "")
            for alias in node.names:
                if alias.name == "*":
                    imports.append({"module": base, "name": "*", "alias": "*", "line": node.lineno})
                    continue
                local = alias.asname or alias.name
                target = ".".join(part for part in (base, alias.name) if part)
                bindings[local] = target
                imports.append({"module": base, "name": alias.name, "alias": local, "line": node.lineno})
    return bindings, imports


def resolve_call(raw, bindings):
    return resolve_binding(raw, bindings) or raw


class FunctionCollector(ast.NodeVisitor):
    def __init__(self, source, module, path, is_test=False, bindings=None):
        self.source = source
        self.module = module
        self.path = path
        self.is_test = is_test
        self.bindings = bindings or {}
        self.class_stack = []
        self.function_stack = []
        self.functions = []

    def visit_ClassDef(self, node):
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def _visit_function(self, node):
        qualified = ".".join(self.class_stack + [node.name])
        visitor = ScopedCallVisitor(self.source, self.bindings, self.class_stack[-1] if self.class_stack else None)
        for statement in node.body:
            visitor.visit(statement)
        complexity, nloc = lizard_metrics(self.source, node)
        calls = visitor.calls
        distinct = sorted({call["normalized"] for call in calls if call["normalized"]})
        record = {
            "id": f"{self.module}:{qualified}@{node.lineno}",
            "module": self.module,
            "path": self.path,
            "name": node.name,
            "qualified_name": qualified,
            "kind": "method" if self.class_stack else "function",
            "class_name": self.class_stack[-1] if self.class_stack else None,
            "line_start": node.lineno,
            "line_end": getattr(node, "end_lineno", node.lineno),
            "function_nloc": nloc,
            "cyclomatic_complexity": complexity,
            "call_count": len(calls),
            "call_out_degree": len(distinct),
            "called_functions": distinct,
            "calls": calls,
            "is_async": isinstance(node, ast.AsyncFunctionDef),
            "is_test": self.is_test,
        }
        self.functions.append(record)
        self.function_stack.append(node.name)
        # Collect nested functions, but do not let their calls enter the parent.
        for statement in node.body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.visit(statement)
        self.function_stack.pop()

    def visit_FunctionDef(self, node):
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node):
        self._visit_function(node)


class TestCallVisitor(ast.NodeVisitor):
    def __init__(self, source, bindings):
        self.source = source
        self.bindings = bindings
        self.calls = []
        self.patch_targets = []

    def visit_Call(self, node):
        raw = dotted_name(node.func) or source_segment(self.source, node.func)
        normalized = resolve_call(raw, self.bindings)
        self.calls.append({"raw": raw, "normalized": normalized, "line": node.lineno})
        for argument in list(node.args) + list(node.keywords):
            value = argument.value if isinstance(argument, ast.keyword) else argument
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                self.patch_targets.append(value.value)
        self.generic_visit(node)

    def visit_Constant(self, node):
        if isinstance(node.value, str) and ("." in node.value):
            self.patch_targets.append(node.value)

    def visit_FunctionDef(self, node):
        for statement in node.body:
            self.visit(statement)

    def visit_AsyncFunctionDef(self, node):
        for statement in node.body:
            self.visit(statement)

    def visit_Lambda(self, node):
        for statement in (node.body,):
            self.visit(statement)

    def visit_ClassDef(self, node):
        for statement in node.body:
            self.visit(statement)


def test_function_nodes(tree):
    result = []
    class_stack = []

    class Visitor(ast.NodeVisitor):
        def visit_ClassDef(self, node):
            class_stack.append(node.name)
            is_test_class = node.name.startswith("Test") or any(
                isinstance(base, ast.Name) and base.id == "TestCase" for base in node.bases
            )
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                    child.name.startswith("test_") or is_test_class
                ):
                    result.append({
                        "id": f"{'.'.join(class_stack)}.{child.name}@{child.lineno}",
                        "name": child.name,
                        "qualified_name": ".".join(class_stack + [child.name]),
                        "line": child.lineno,
                    })
                self.visit(child)
            class_stack.pop()

        def visit_FunctionDef(self, node):
            if node.name.startswith("test_"):
                result.append({
                    "id": f"{node.name}@{node.lineno}",
                    "name": node.name,
                    "qualified_name": node.name,
                    "line": node.lineno,
                })
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    self.visit(child)

        visit_AsyncFunctionDef = visit_FunctionDef

    Visitor().visit(tree)
    seen = set()
    return [item for item in result if not (item["id"] in seen or seen.add(item["id"]))]


def parse_file(root, rel_path, is_test):
    full = root / rel_path
    try:
        source = full.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(rel_path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        return {"path": posix(rel_path), "parse_status": "error", "error": str(exc), "functions": []}
    module = module_name(posix(rel_path))
    bindings, imports = import_bindings(tree, module)
    collector = FunctionCollector(source, module, posix(rel_path), is_test, bindings)
    collector.visit(tree)
    record = {
        "path": posix(rel_path),
        "module": module,
        "parse_status": "ok",
        "imports": imports,
        "bindings": bindings,
        "functions": collector.functions,
    }
    if is_test:
        test_calls = TestCallVisitor(source, bindings)
        test_calls.visit(tree)
        record["test_functions"] = test_function_nodes(tree)
        record["calls"] = test_calls.calls
        record["patch_targets"] = sorted(set(test_calls.patch_targets))
        record["frameworks"] = detect_frameworks(tree, source)
    return record


def detect_frameworks(tree, source):
    text = source.lower()
    frameworks = []
    if "pytest" in text or any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_") for n in ast.walk(tree)):
        frameworks.append("pytest")
    if "unittest" in text or any(isinstance(n, ast.Name) and n.id == "TestCase" for n in ast.walk(tree)):
        frameworks.append("unittest")
    return sorted(set(frameworks))


def match_sources(source_files, test_files):
    functions = [f for file in source_files for f in file["functions"]]
    by_module = defaultdict(list)
    by_symbol = defaultdict(list)
    for function in functions:
        by_module[function["module"]].append(function)
        by_symbol[f"{function['module']}.{function['qualified_name']}"] .append(function)
        by_symbol[f"{function['module']}.{function['name']}"] .append(function)

    matches = []
    for test_file in test_files:
        if test_file.get("parse_status") != "ok":
            continue
        imported_modules = {item["module"] for item in test_file.get("imports", []) if item.get("module")}
        imported_symbols = {
            ".".join(part for part in (item.get("module"), item.get("name")) if part)
            for item in test_file.get("imports", []) if item.get("name") not in (None, "*")
        }
        calls = test_file.get("calls", [])
        patch_targets = test_file.get("patch_targets", [])
        test_ids = [item["id"] for item in test_file.get("test_functions", [])]
        file_stem = Path(test_file["path"]).stem.lower().removeprefix("test_").removesuffix("_test")
        for function in functions:
            source_module = function["module"]
            symbol = f"{source_module}.{function['qualified_name']}"
            short_symbol = f"{source_module}.{function['name']}"
            evidence = []
            confidence = "none"
            if source_module in imported_modules:
                evidence.append(f"imports module {source_module}")
            if symbol in imported_symbols or short_symbol in imported_symbols:
                evidence.append(f"imports symbol {symbol}")
                confidence = "high"
            resolved_calls = {call.get("normalized") for call in calls}
            if symbol in resolved_calls or short_symbol in resolved_calls:
                evidence.append(f"calls {symbol}")
                confidence = "high"
            if any(symbol in target or short_symbol in target for target in patch_targets):
                evidence.append(f"patch target references {symbol}")
                confidence = max_confidence(confidence, "medium")
            if not evidence and file_stem and (
                file_stem == Path(function["path"]).stem.lower()
                or file_stem == function["name"].lower()
            ):
                evidence.append("test/source filename convention")
                confidence = "low"
            if evidence:
                has_function_relation = any(
                    marker in " ".join(evidence)
                    for marker in ("imports symbol", "calls ", "patch target")
                )
                matches.append({
                    "source_id": function["id"],
                    "source_file": function["path"],
                    "source_function": function["qualified_name"],
                    "test_file": test_file["path"],
                    "test_functions": test_ids,
                    "confidence": confidence,
                    "has_module_test": True,
                    "has_corresponding_test": has_function_relation,
                    "evidence": evidence,
                })
    return matches


def max_confidence(current, candidate):
    order = {"none": 0, "low": 1, "medium": 2, "high": 3}
    return candidate if order[candidate] > order[current] else current


def discover_files(root):
    files = []
    for path in sorted(root.rglob("*.py")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if is_test_path(posix(rel)):
            files.append((rel, True))
        elif is_source_path(posix(rel)):
            files.append((rel, False))
    return files


def analyze(root):
    source_files = []
    test_files = []
    diagnostics = []
    for rel, is_test in discover_files(root):
        record = parse_file(root, rel, is_test)
        if record["parse_status"] == "error":
            diagnostics.append({"path": record["path"], "error": record["error"]})
        if is_test:
            test_files.append(record)
        else:
            source_files.append(record)
    matches = match_sources(source_files, test_files)
    by_source = defaultdict(list)
    for match in matches:
        by_source[match["source_id"]].append(match)
    for file_record in source_files:
        for function in file_record["functions"]:
            function_matches = by_source.get(function["id"], [])
            function["has_module_test"] = bool(function_matches)
            function["has_corresponding_test"] = any(m["has_corresponding_test"] for m in function_matches)
            function["test_match_confidence"] = max(
                (m["confidence"] for m in function_matches),
                key=lambda x: {"none": 0, "low": 1, "medium": 2, "high": 3}[x],
                default="none",
            )
            function["matching_test_files"] = sorted({m["test_file"] for m in function_matches})
    all_functions = [f for file in source_files for f in file["functions"]]
    return {
        "schema_version": 1,
        "analysis_mode": "static",
        "project_root": str(root),
        "summary": {
            "source_files": len(source_files),
            "test_files": len(test_files),
            "source_functions": len(all_functions),
            "test_functions": sum(len(f.get("test_functions", [])) for f in test_files),
            "parse_errors": len(diagnostics),
            "matched_source_functions": sum(bool(f.get("matching_test_files")) for f in all_functions),
            "corresponding_test_functions": sum(f.get("has_corresponding_test", False) for f in all_functions),
        },
        "source_files": source_files,
        "test_files": test_files,
        "matches": matches,
        "diagnostics": diagnostics,
    }


def write_csv(report, path):
    fields = [
        "source_file", "function_name", "qualified_name", "function_nloc",
        "cyclomatic_complexity", "call_count", "call_out_degree", "called_functions",
        "has_module_test", "has_corresponding_test", "test_match_confidence",
        "matching_test_files",
    ]
    functions = [f for file in report["source_files"] for f in file["functions"]]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for function in functions:
            writer.writerow({
                "source_file": function["path"],
                "function_name": function["name"],
                "qualified_name": function["qualified_name"],
                "function_nloc": function["function_nloc"],
                "cyclomatic_complexity": function["cyclomatic_complexity"],
                "call_count": function["call_count"],
                "call_out_degree": function["call_out_degree"],
                "called_functions": ";".join(function["called_functions"]),
                "has_module_test": function.get("has_module_test", False),
                "has_corresponding_test": function.get("has_corresponding_test", False),
                "test_match_confidence": function.get("test_match_confidence", "none"),
                "matching_test_files": ";".join(function.get("matching_test_files", [])),
            })


def main():
    parser = argparse.ArgumentParser(description="Static Python function/test analysis")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--csv-output", required=True)
    args = parser.parse_args()
    report = analyze(Path(args.project_root).resolve())
    with open(args.json_output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    write_csv(report, args.csv_output)
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
