#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract Java methods that pass fixed complexity thresholds.

A method is retained only when all three conditions hold:
    LOC >= 50
    cyclomatic complexity >= 10
    unique callee-expression count >= 5

This version does not use the external StratifiedFunctionSelector or
FileQualityAnalyzer. It recursively discovers production .java files itself,
excluding likely test files/directories, and keeps every method that passes the
thresholds.
"""

import argparse
import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# from tree_sitter import Language, Parser
# import tree_sitter_java
from multi_parser import java_parser

try:
    import lizard
except ImportError:  # pragma: no cover - fallback is used only without lizard
    lizard = None


# JAVA_LANGUAGE = Language(tree_sitter_java.language())
CLASS_NODE_TYPES = {
    "class_declaration",
    "interface_declaration",
    "enum_declaration",
    "record_declaration",
    "annotation_type_declaration",
}
BODY_NODE_TYPES = {"class_body", "interface_body", "enum_body", "annotation_type_body"}
MODIFIER_TYPES = {
    "public", "private", "protected", "static", "abstract", "final",
    "synchronized", "native", "strictfp", "default", "transient", "volatile",
}

IGNORED_DIRS = {
    'test', 'tests', '__tests__', '__pycache__', '.git', '.svn', '.hg',
    'venv', 'env', '.env', 'virtualenv', 'envs',
    '.vscode', '.idea', '.pytest_cache', '.mypy_cache',
    'build', 'dist', '*.egg-info', 'node_modules',
    'target', 'doc', 'docs', 'example', 'examples', 'coverage', 'script', 'scripts', 'benchmarks',
    'benchmark', '.cargo', '.direnv', 'demos'
}


def is_ignored_dir_name(name: str) -> bool:
    """Return whether a directory is outside the production extraction scope.

    Besides exact names such as ``benchmarks``, Java repositories commonly use
    module names such as ``parquet-benchmarks`` or ``foo_benchmark``.  Those
    modules contain benchmark drivers/JMH fixtures rather than production
    functions and should be excluded as well.
    """

    normalized = name.lower()
    if normalized in IGNORED_DIRS:
        return True
    return bool(re.search(r"(?:^|[-_.])benchmarks?(?:$|[-_.])", normalized))

# IGNORED_DIRS = {
#     ".git", ".svn", ".hg", ".idea", ".vscode", ".gradle", ".mvn",
#     "target", "build", "out", "bin", "dist", "generated-sources",
#     "node_modules", "vendor", "coverage", "reports", "report",
#     "test", "tests", "__tests__",
# }
TEST_FILE_PATTERNS = [
    re.compile(r"^Test.*\.java$", re.IGNORECASE),
    re.compile(r".*Test\.java$", re.IGNORECASE),
    re.compile(r".*Tests\.java$", re.IGNORECASE),
    re.compile(r".*TestCase\.java$", re.IGNORECASE),
    re.compile(r".*IT\.java$"),  # common integration-test suffix
]

def get_point_row(point):
    """兼容 Tree-sitter 0.21.3 的元组和新版 Point 对象。"""
    if isinstance(point, tuple):
        return point[0]
    return point.row

def create_java_parser():
    """Create a Tree-sitter Java parser using the modern API."""
    return java_parser


def get_node_text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def get_name_node(node):
    """Get a declaration's name node, with a small grammar-version fallback."""
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return name_node
    for child in node.children:
        if child.type in {"identifier", "type_identifier"}:
            return child
    return None


def get_modifiers(node) -> List[str]:
    """Extract Java modifiers across common tree-sitter-java grammar layouts."""
    modifiers: List[str] = []
    for child in node.children:
        if child.type == "modifier":
            text = child.text.decode("utf-8", errors="replace").strip()
            # A modifier wrapper can include annotations; keep recognized words.
            for token in text.split():
                token = token.rstrip(";")
                if token in MODIFIER_TYPES:
                    modifiers.append(token)
        elif child.type in MODIFIER_TYPES:
            modifiers.append(child.type)
        elif child.type == "modifiers":
            for mod_child in child.children:
                if mod_child.type == "modifier":
                    text = mod_child.text.decode("utf-8", errors="replace").strip()
                    for token in text.split():
                        token = token.rstrip(";")
                        if token in MODIFIER_TYPES:
                            modifiers.append(token)
                elif mod_child.type in MODIFIER_TYPES:
                    modifiers.append(mod_child.type)
    return list(dict.fromkeys(modifiers))


def is_deprecated(node) -> bool:
    """Return True when a declaration contains a Deprecated annotation."""
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type in {"annotation", "marker_annotation"}:
            text = current.text.decode("utf-8", errors="replace")
            if "Deprecated" in text:
                return True
        # Only inspect modifier/declaration metadata, not arbitrary method bodies.
        if current is node or current.type in {"modifiers", "modifier"}:
            stack.extend(current.children)
    return False


def extract_imports(source: bytes) -> List[str]:
    text = source.decode("utf-8", errors="ignore")
    return [m.strip() for m in re.findall(
        r"^\s*import\s+(?:static\s+)?[^;]+;", text, flags=re.MULTILINE
    )]


def get_class_superclasses(class_node, source: bytes) -> List[str]:
    """Extract simple superclass/interface names for lightweight inheritance handling."""
    names: List[str] = []
    for child in class_node.children:
        if child.type in {"superclass", "super_interfaces", "extends_interfaces", "extends_interfaces"}:
            for sub in child.named_children:
                if sub.type in {"type_identifier", "scoped_type_identifier", "generic_type"}:
                    text = get_node_text(sub, source).strip()
                    # Keep a simple name for lookup; full generic syntax is not needed here.
                    names.append(text.split("<", 1)[0].split(".")[-1])
    return list(dict.fromkeys(names))


def get_method_name(method_node, source: bytes) -> str:
    name_node = get_name_node(method_node)
    return get_node_text(name_node, source).strip() if name_node is not None else ""


def get_method_key(method_node, method_name: str, source: bytes) -> str:
    """Include the parameter-list text so overloads do not overwrite one another."""
    params = method_node.child_by_field_name("parameters")
    if params is None:
        params = next((c for c in method_node.children if c.type == "formal_parameters"), None)
    params_text = get_node_text(params, source).strip() if params is not None else "()"
    return f"{method_name}{params_text}"


def discover_java_files(project_root: str) -> List[str]:
    """Recursively collect production Java files, excluding test/build directories."""
    root_path = Path(project_root).resolve()
    java_files: List[str] = []
    for current_root, dirs, files in os.walk(root_path):
        # Mutate dirs in place so os.walk does not descend into ignored folders.
        dirs[:] = [d for d in dirs if not is_ignored_dir_name(d) and not d.startswith(".")]
        for filename in files:
            if not filename.endswith(".java"):
                continue
            if any(pattern.match(filename) for pattern in TEST_FILE_PATTERNS):
                continue
            full_path = Path(current_root) / filename
            relative_parts = full_path.relative_to(root_path).parts[:-1]
            if any(is_ignored_dir_name(part) for part in relative_parts):
                continue
            java_files.append(str(full_path))
    return sorted(set(java_files))


class JavaProjectTestScopeExtractor:
    """Parse Java production files and keep every method meeting all thresholds."""

    def __init__(
        self,
        project_root: str,
        file_list: List[str],
        output_file: Optional[str] = None,
        min_loc_threshold: int = 50,
        min_complexity_threshold: int = 10,
        min_outgoing_degree_threshold: int = 5,
    ):
        self.project_root = str(Path(project_root).resolve())
        self.files = file_list
        self.output_file = output_file
        self.min_loc_threshold = min_loc_threshold
        self.min_complexity_threshold = min_complexity_threshold
        self.min_outgoing_degree_threshold = min_outgoing_degree_threshold
        self.parser = create_java_parser()
        # Keyed by simple class name to keep compatibility with the original inheritance code.
        self.classes: Dict[str, Dict[str, Any]] = {}
        self.stats: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

        if lizard is None:
            print("警告：未安装 lizard，将使用近似方法计算圈复杂度。建议运行 pip install lizard")

    def _compute_complexity_and_loc(self, method_code: str) -> Tuple[int, int, int]:
        """Return cyclomatic complexity, non-blank LOC, and parameter count."""
        if lizard is not None:
            try:
                report = lizard.analyze_file.analyze_source_code("Temp.java", method_code)
                if report.function_list:
                    fn = report.function_list[0]
                    complexity = int(getattr(fn, "cyclomatic_complexity", 1))
                    loc = int(getattr(fn, "nloc", 0))
                    params = getattr(fn, "full_parameters", []) or []
                    return complexity, loc, len(params)
            except Exception as exc:
                print(f"警告：Lizard 分析方法失败，将使用近似值：{exc}")

        nonblank_lines = [line for line in method_code.splitlines() if line.strip()]
        loc = len(nonblank_lines)
        # Lightweight fallback; unlike Lizard this is only an approximation.
        branches = len(re.findall(
            r"\b(if|for|while|case|catch)\b|&&|\|\||\?(?!\.)", method_code
        ))
        complexity = 1 + branches
        signature = method_code.splitlines()[0] if method_code.splitlines() else ""
        params_match = re.search(r"\((.*?)\)", signature)
        param_text = params_match.group(1).strip() if params_match else ""
        param_count = len([p for p in param_text.split(",") if p.strip()]) if param_text else 0
        return complexity, loc, param_count

    def _compute_outgoing_degree(self, method_node, source: bytes) -> int:
        """Count unique Java call expressions within this method using Tree-sitter.

        This is a syntax-level approximation, not a fully resolved call graph.
        Repeated identical expressions count once. Calls inside nested classes or
        lambdas are not attributed to the enclosing method. Object creation is
        counted as a distinct constructor-like call expression (e.g. ``new Foo``).
        """
        callees: Set[str] = set()
        nested_scopes = {
            "method_declaration", "constructor_declaration", "class_declaration",
            "interface_declaration", "enum_declaration", "record_declaration",
            "annotation_type_declaration", "lambda_expression", "anonymous_class_body",
        }

        def visit(node, is_root: bool = False) -> None:
            if not is_root and node.type in nested_scopes:
                return

            if node.type == "method_invocation":
                name_node = node.child_by_field_name("name")
                object_node = node.child_by_field_name("object")
                if name_node is not None:
                    name = get_node_text(name_node, source).strip()
                    if object_node is not None:
                        obj = get_node_text(object_node, source).strip()
                        callees.add(f"{obj}.{name}")
                    else:
                        callees.add(name)

            elif node.type == "object_creation_expression":
                type_node = node.child_by_field_name("type")
                if type_node is not None:
                    callees.add("new " + get_node_text(type_node, source).strip())

            for child in node.children:
                visit(child)

        visit(method_node, is_root=True)
        return len(callees)

    def _parse_project(self) -> None:
        print(f"开始解析项目，文件数量: {len(self.files)}")
        for file_path in self.files:
            try:
                self._parse_file(file_path)
            except Exception as exc:
                print(f"解析文件失败 {file_path}: {exc}")

    def _parse_file(self, file_path: str) -> None:
        with open(file_path, "rb") as f:
            source = f.read()
        tree = self.parser.parse(source)
        imports = extract_imports(source)
        package_match = re.search(rb"\bpackage\s+([\w.]+)\s*;", source)
        package_name = package_match.group(1).decode("utf-8", errors="replace") if package_match else ""

        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            if node.type in CLASS_NODE_TYPES:
                self._parse_class_node(node, source, file_path, imports, package_name)
            # Continue traversal so nested/local classes are discoverable too.
            stack.extend(reversed(node.children))

    def _parse_class_node(
        self, class_node, source: bytes, file_path: str,
        imports: List[str], package_name: str
    ) -> None:
        if is_deprecated(class_node):
            return

        name_node = get_name_node(class_node)
        if name_node is None:
            return
        class_name = get_node_text(name_node, source).strip()
        if not class_name:
            return

        modifiers = get_modifiers(class_node)
        # A public method is not externally callable when it belongs to a
        # private nested type.  Walk the enclosing type declarations so both
        # candidate filtering and the stored FQN reflect Java's real access
        # boundary (for example ParquetFileReader.Chunk rather than Chunk).
        enclosing_types = []
        parent = class_node.parent
        while parent is not None:
            if parent.type in CLASS_NODE_TYPES:
                enclosing_name = get_name_node(parent)
                if enclosing_name is not None:
                    name = get_node_text(enclosing_name, source).strip()
                    if name:
                        enclosing_types.append((name, get_modifiers(parent)))
            parent = parent.parent
        enclosing_types.reverse()
        class_path = [name for name, _ in enclosing_types] + [class_name]
        full_class_name = ".".join(
            ([package_name] if package_name else []) + class_path)
        is_effectively_private = (
            "private" in modifiers
            or any("private" in ancestor_modifiers
                   for _, ancestor_modifiers in enclosing_types)
        )
        is_abstract = "abstract" in modifiers or class_node.type == "interface_declaration"
        superclasses = get_class_superclasses(class_node, source)
        body_node = next((c for c in class_node.children if c.type in BODY_NODE_TYPES), None)

        methods: Dict[str, Dict[str, Any]] = {}
        constructor_codes: List[str] = []
        field_codes: List[str] = []

        if body_node is not None:
            for child in body_node.children:
                if child.type == "method_declaration":
                    if is_deprecated(child):
                        continue
                    method_name = get_method_name(child, source)
                    if not method_name:
                        continue
                    method_modifiers = get_modifiers(child)

                    if class_node.type == "interface_declaration":
                        has_body = any(c.type == "block" for c in child.children)
                        if not has_body and "default" not in method_modifiers and "static" not in method_modifiers:
                            if "abstract" not in method_modifiers:
                                method_modifiers.append("abstract")

                    method_code = get_node_text(child, source)
                    complexity, loc, param_count = self._compute_complexity_and_loc(method_code)
                    outgoing_degree = self._compute_outgoing_degree(child, source)

                    return_type_node = child.child_by_field_name("type")
                    return_type_text = get_node_text(return_type_node, source).lower() if return_type_node else ""
                    is_async = (
                        "completablefuture" in return_type_text
                        or re.search(r"\bfuture\b", return_type_text) is not None
                        or "@Async" in method_code
                    )

                    method_key = get_method_key(child, method_name, source)
                    methods[method_key] = {
                        "name": method_name,
                        "method_key": method_key,
                        "src_file": file_path,
                        "code": method_code,
                        "is_static": "static" in method_modifiers,
                        "is_abstract": "abstract" in method_modifiers,
                        "is_private": "private" in method_modifiers,
                        "is_protected": "protected" in method_modifiers,
                        "is_public": "public" in method_modifiers,
                        "loc": loc,
                        "complexity": complexity,
                        "param_count": param_count,
                        "outgoing_degree": outgoing_degree,
                        "unique_callee_count": outgoing_degree,
                        "is_async": bool(is_async),
                        "type": "method",
                        "class_name": class_name,
                        "full_class_name": full_class_name,
                        "modifiers": method_modifiers,
                        "imports": imports,
                        "start_line": get_point_row(child.start_point) + 1,
                        "end_line": get_point_row(child.end_point) + 1,
                    }

                elif child.type == "constructor_declaration":
                    if not is_deprecated(child) and "private" not in get_modifiers(child):
                        constructor_codes.append(get_node_text(child, source))

                elif child.type == "field_declaration":
                    if not is_deprecated(child) and "private" not in get_modifiers(child):
                        field_codes.append(get_node_text(child, source))

        key = full_class_name
        self.classes[key] = {
            "name": class_name,
            "full_class_name": key,
            "abstract": is_abstract,
            "is_effectively_private": is_effectively_private,
            "methods": methods,
            "constructor_codes": constructor_codes,
            "field_codes": field_codes,
            "superclasses": superclasses,
            "file": file_path,
            "imports": imports,
        }

    def _should_filter_method(self, method_info: Dict[str, Any]) -> Tuple[bool, str]:
        """Reject a method if it fails any one of the three thresholds."""
        reasons = []
        if method_info.get("loc", 0) < self.min_loc_threshold:
            reasons.append(f"loc<{self.min_loc_threshold}")
        if method_info.get("complexity", 0) < self.min_complexity_threshold:
            reasons.append(f"complexity<{self.min_complexity_threshold}")
        unique_callee_count = method_info.get(
            "unique_callee_count", method_info.get("outgoing_degree", 0)
        )
        if unique_callee_count < self.min_outgoing_degree_threshold:
            reasons.append(f"unique_callee_count<{self.min_outgoing_degree_threshold}")
        return bool(reasons), ",".join(reasons)

    # def _compute_test_scope_for_class(self, class_key: str) -> List[Dict[str, Any]]:
    #     cls = self.classes.get(class_key)
    #     if not cls:
    #         return []
    #     methods = cls["methods"]

    #     if cls["abstract"]:
    #         # Preserve the original policy: only static methods in abstract classes
    #         # become direct test candidates.
    #         return [m for m in methods.values() if m["is_static"]]

    #     # Public/protected/package-private methods can be candidates; private methods are omitted.
    #     return [m for m in methods.values() if not m["is_private"]]

    def _compute_test_scope_for_class(self, class_key: str) -> List[Dict[str, Any]]:
        cls = self.classes.get(class_key)
        if not cls:
            return []
        # A public/protected/package-private member of a private nested type
        # remains inaccessible to an external test class.  Reflection is not
        # the normal API surface and must not make such methods candidates.
        if cls.get("is_effectively_private", False):
            return []

        methods = [
            m for m in cls["methods"].values()
            if not m.get("is_private", False)
        ]

        if cls["abstract"]:
            return [m for m in methods if m["is_static"]]

        return methods

    def _gen_test_file_path(self, file_path: str, function_name: str) -> str:
        rel = os.path.relpath(file_path, self.project_root)
        rel_no_ext = os.path.splitext(rel)[0]
        path_parts = list(Path(rel_no_ext).parts)
        for index in range(len(path_parts) - 1):
            if path_parts[index] == "main" and path_parts[index + 1] == "java":
                path_parts[index] = "test"
                break
        rel_no_ext = Path(*path_parts).as_posix()
        package_dir = os.path.dirname(rel_no_ext)
        class_name = os.path.basename(rel_no_ext)
        method_capitalized = function_name[:1].upper() + function_name[1:] if function_name else "Method"
        return f"{package_dir}/{class_name}{method_capitalized}Tests.java"

    def extract_and_select_functions(self) -> List[Dict[str, Any]]:
        """Parse all supplied files, filter methods, and keep all passing methods.

        Despite retaining the historical method name for caller compatibility, this
        function no longer invokes any external function selector or sampling logic.
        """
        self._parse_project()
        selected_methods: List[Dict[str, Any]] = []
        self.stats.clear()

        methods_by_file: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for class_info in self.classes.values():
            for method in self._compute_test_scope_for_class(class_info["full_class_name"]):
                method = dict(method)
                method["class_name"] = class_info["name"]
                method["full_class_name"] = class_info["full_class_name"]
                method["class_constructor"] = class_info["constructor_codes"]
                method["class_fields"] = class_info["field_codes"]
                method["imports"] = class_info["imports"]
                methods_by_file[method["src_file"]].append(method)

        for file_path, file_methods in sorted(methods_by_file.items()):
            file_name = os.path.basename(file_path)
            self.stats[file_name]["total"] = len(file_methods)
            self.stats[file_name]["public"] = sum(1 for m in file_methods if m.get("is_public"))

            passed = 0
            filtered = 0
            for method in file_methods:
                should_filter, reason = self._should_filter_method(method)
                if should_filter:
                    filtered += 1
                    continue

                passed += 1
                method_info = {
                    "project_root": self.project_root,
                    "name": method["name"],
                    "method_key": method.get("method_key", method["name"]),
                    "src_file": os.path.relpath(method["src_file"], self.project_root),
                    "test_file": self._gen_test_file_path(method["src_file"], method["name"]),
                    "code": method["code"],
                    "is_async": method.get("is_async", False),
                    "is_static": method.get("is_static", False),
                    "type": method.get("type", "method"),
                    "loc": method.get("loc", 0),
                    "complexity": method.get("complexity", 0),
                    "outgoing_degree": method.get("outgoing_degree", 0),
                    "unique_callee_count": method.get(
                        "unique_callee_count", method.get("outgoing_degree", 0)
                    ),
                    "start_line": method.get("start_line", 0),
                    "end_line": method.get("end_line", 0),
                    "class_name": method.get("class_name"),
                    "full_class_name": method.get("full_class_name"),
                    "class_constructor": method.get("class_constructor", []),
                    "class_fields": method.get("class_fields", []),
                    "imports": method.get("imports", []),
                }
                selected_methods.append(method_info)

            self.stats[file_name]["candidates"] = passed
            self.stats[file_name]["filtered"] = filtered
            print(
                f"{file_name}: 原始方法={len(file_methods)}, "
                f"保留={passed}, 过滤={filtered}"
            )

        if self.output_file:
            self._save_to_json(selected_methods)
        self._print_statistics_report(len(selected_methods))
        return selected_methods

    def _print_statistics_report(self, selected_count: int) -> None:
        total_methods = sum(stats["total"] for stats in self.stats.values())
        total_candidates = sum(stats["candidates"] for stats in self.stats.values())
        total_filtered = sum(stats["filtered"] for stats in self.stats.values())
        print("\n" + "=" * 60)
        print("统计报告（未使用外部函数选择器）")
        print("=" * 60)
        print(f"解析到的候选方法总数: {total_methods}")
        print(f"通过全部阈值的方法数: {total_candidates}")
        print(f"过滤方法数: {total_filtered}")
        print(f"最终输出方法数: {selected_count}")
        print(f"涉及文件数: {len(self.stats)}")
        print(
            "筛选条件："
            f"LOC >= {self.min_loc_threshold}, "
            f"CC >= {self.min_complexity_threshold}, "
            f"unique callee expressions >= {self.min_outgoing_degree_threshold}"
        )

    def _save_to_json(self, data: List[Dict[str, Any]]) -> None:
        if not self.output_file:
            return
        output_path = Path(self.output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"\n结果已保存到: {output_path}")

    def save_to_json(self, output_file: Optional[str] = None) -> None:
        """Compatibility helper: update output path and run extraction."""
        if output_file:
            self.output_file = output_file
        self.extract_and_select_functions()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="从 Java 项目收集生产源码，并保留达到三个复杂度阈值的方法。"
    )
    parser.add_argument("--project-root", required=True, help="Java 项目根目录")
    parser.add_argument("--output", default="selected_methods.json", help="输出 JSON 路径")
    parser.add_argument("--min-loc", type=int, default=50, help="最小非空代码行数，默认 50")
    parser.add_argument("--min-complexity", type=int, default=10, help="最小圈复杂度，默认 10")
    parser.add_argument("--min-outgoing-degree", type=int, default=5, help="最小不同调用表达式数，默认 5")
    args = parser.parse_args()

    project_root = str(Path(args.project_root).resolve())
    java_files = discover_java_files(project_root)
    print(f"项目根目录: {project_root}")
    print(f"发现生产 Java 文件: {len(java_files)}（已排除测试文件/目录及常见构建目录）")

    extractor = JavaProjectTestScopeExtractor(
        project_root=project_root,
        file_list=java_files,
        output_file=args.output,
        min_loc_threshold=args.min_loc,
        min_complexity_threshold=args.min_complexity,
        min_outgoing_degree_threshold=args.min_outgoing_degree,
    )
    selected = extractor.extract_and_select_functions()
    print(f"\n总共保留 {len(selected)} 个方法。")


if __name__ == "__main__":
    main()
