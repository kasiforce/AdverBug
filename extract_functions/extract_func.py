#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build concise static context bundles for function specification generation.

Compatible with tree-sitter==0.21.3 and tree_sitter_languages.
No tests are executed and no project compilation is required.

The context deliberately includes only:
  Priority 1: target function/signature, comments/docstring, direct related tests,
              parameter/return types, and necessary local type definitions.
  Priority 2: direct callers, direct dependency implementations, and the target
              class's constructors and fields.

Indirect callers, transitive call chains, module-level call sites, and broad
repository context are intentionally omitted.

Examples:
  # Add context to every function record produced by a filter script.
  python extract_spec_context.py --repo projects/flink \
      --selected-functions flink.json --output flink_with_context.json

  # Extract context for a single function.
  python extract_spec_context.py --repo projects/flink \
      --target-file flink-core/src/main/java/example/Foo.java \
      --target-name process --target-class Foo --target-line 120 \
      --output process_context.json
"""

import argparse
import json
import os
import posixpath
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

try:
    import tree_sitter_languages
    from tree_sitter import Parser
except ImportError as exc:
    print(
        "Missing Tree-sitter packages. For your pinned API, install:\n"
        "  python -m pip install tree-sitter==0.21.3 tree-sitter-languages==1.10.2",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc


LANG_BY_EXT = {
    ".py": "python",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
}

FUNCTION_TYPES = {
    "python": {"function_definition"},
    "java": {"method_declaration", "constructor_declaration"},
    "javascript": {
        "function_declaration", "generator_function_declaration",
        "method_definition", "arrow_function", "function_expression",
        "generator_function", "function",
    },
}

CLASS_TYPES = {
    "python": {"class_definition"},
    "java": {
        "class_declaration", "interface_declaration", "enum_declaration",
        "record_declaration", "annotation_type_declaration",
    },
    "javascript": {"class_declaration", "class"},
}

CALL_TYPES = {
    "python": {"call"},
    "java": {
        "method_invocation", "object_creation_expression",
        "explicit_constructor_invocation",
    },
    "javascript": {"call_expression", "new_expression"},
}

IMPORT_TYPES = {
    "python": {"import_statement", "import_from_statement"},
    "java": {"import_declaration"},
    "javascript": {"import_statement"},
}

TYPE_BODY_TYPES = {
    "python": {"block"},
    "java": {"class_body", "interface_body", "enum_body", "annotation_type_body"},
    "javascript": {"class_body"},
}

DEFAULT_EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode", "node_modules", "vendor",
    "dist", "build", "target", "coverage", ".coverage", ".venv", "venv",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".tox", "site-packages",
    "generated-sources", "out", "bin",
}

TEST_NAME_PATTERNS = (
    re.compile(r"^test_", re.IGNORECASE),
    re.compile(r"_test$", re.IGNORECASE),
    re.compile(r"tests?$", re.IGNORECASE),
)

PARSERS: Dict[str, Any] = {}


def make_parser(language: str):
    """Create the old-API parser expected by tree-sitter==0.21.3."""
    parser = Parser()
    parser.set_language(tree_sitter_languages.get_language(language))
    return parser


def get_parser(language: str):
    parser = PARSERS.get(language)
    if parser is None:
        parser = make_parser(language)
        PARSERS[language] = parser
    return parser


def point_row(point: Any) -> int:
    """Tree-sitter 0.21.3 exposes points as (row, column) tuples."""
    if isinstance(point, (tuple, list)):
        return int(point[0])
    return int(point.row)


def node_text(node: Any, source: bytes) -> str:
    if node is None:
        return ""
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def field_node(node: Any, field_name: str):
    try:
        return node.child_by_field_name(field_name)
    except Exception:
        return None


def field_text(node: Any, field_name: str, source: bytes) -> str:
    return node_text(field_node(node, field_name), source).strip()


def direct_identifier(node: Any, source: bytes) -> str:
    named_types = {"identifier", "type_identifier", "property_identifier", "field_identifier"}
    for child in node.children:
        if child.type in named_types:
            return node_text(child, source).strip()
    return ""


def walk(node: Any) -> Iterable[Any]:
    """Iterative depth-first traversal, avoiding Python recursion for deep files."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def node_key(path: str, node: Any) -> Tuple[str, int, int, str]:
    return path, int(node.start_byte), int(node.end_byte), str(node.type)


def nearest_function_node(node: Any, language: str):
    current = node.parent
    while current is not None:
        if current.type in FUNCTION_TYPES[language]:
            return current
        current = current.parent
    return None


def nearest_class_name(node: Any, language: str, source: bytes) -> str:
    current = node.parent
    names = []
    while current is not None:
        if current.type in CLASS_TYPES[language]:
            name = field_text(current, "name", source) or direct_identifier(current, source)
            if name:
                names.append(name)
        current = current.parent
    return ".".join(reversed(names))


def declaration_full_node(node: Any, language: str):
    if language == "python" and node.type == "function_definition":
        parent = node.parent
        if parent is not None and parent.type == "decorated_definition":
            return parent
    return node


def leading_comments(source: bytes, declaration_start_row: int, max_lines: int = 25) -> str:
    """Get contiguous comments/doc comments immediately above a declaration."""
    lines = source.decode("utf-8", errors="replace").splitlines()
    index = min(declaration_start_row - 1, len(lines) - 1)
    collected = []
    while index >= 0 and len(collected) < max_lines:
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            break
        if (
            stripped.startswith(("#", "//", "/*", "*", "*/", "///", "//!", "@"))
            or stripped.startswith("<!--")
            or stripped.endswith("*/")
        ):
            collected.append(line)
            index -= 1
            continue
        break
    return "\n".join(reversed(collected)).strip()


def extract_python_docstring(function_node: Any, source: bytes) -> str:
    body = field_node(function_node, "body")
    if body is None:
        return ""
    first = next((child for child in body.named_children if child.type != "comment"), None)
    if first is None or first.type != "expression_statement" or not first.named_children:
        return ""
    expression = first.named_children[0]
    if expression.type not in {"string", "concatenated_string"}:
        return ""
    raw = node_text(expression, source).strip()
    match = re.match(r"(?is)^([rubf]*)('''|\"\"\"|'|\")", raw)
    if match:
        quote = match.group(2)
        if raw.endswith(quote) and len(raw) >= len(match.group(0)) + len(quote):
            return raw[len(match.group(0)):-len(quote)]
    return raw


def callable_name(node: Any, language: str, source: bytes) -> str:
    name = field_text(node, "name", source) or direct_identifier(node, source)
    if language == "javascript" and node.type in {
        "arrow_function", "function_expression", "generator_function", "function"
    }:
        if not name:
            parent = node.parent
            while parent is not None and parent.type not in {
                "variable_declarator", "assignment_expression", "lexical_declaration", "variable_declaration"
            }:
                if parent.type in FUNCTION_TYPES[language] and parent != node:
                    break
                parent = parent.parent
            if parent is not None and parent.type == "variable_declarator":
                name = field_text(parent, "name", source) or name
            elif parent is not None and parent.type == "assignment_expression":
                name = field_text(parent, "left", source) or name
        if not name:
            callback_name, is_test = infer_js_test_callback(node, source)
            if callback_name:
                return callback_name
            name = f"<anonymous>@{point_row(node.start_point) + 1}"
    if not name:
        name = f"<anonymous>@{point_row(node.start_point) + 1}"
    return name


def infer_js_test_callback(node: Any, source: bytes) -> Tuple[str, bool]:
    current = node.parent
    while current is not None and current.type not in {"call_expression", "program", "statement_block"}:
        current = current.parent
    if current is None or current.type != "call_expression":
        return "", False
    function = field_node(current, "function")
    callee_text = node_text(function, source).strip() if function is not None else ""
    if callee_text.split(".")[-1] not in {"test", "it", "fit", "xit", "specify"}:
        return "", False
    args = field_node(current, "arguments")
    if args is not None:
        for child in args.named_children:
            if child.type in {"string", "template_string"}:
                label = node_text(child, source).strip().strip("`\"'")
                return (f"test_case::{label}", True) if label else ("", False)
            if child == node or child.type in {"arrow_function", "function_expression"}:
                break
    return f"test_case@{point_row(node.start_point) + 1}", True


def get_callable_signature(node: Any, language: str, source: bytes) -> str:
    body = field_node(node, "body")
    if body is not None and body.start_byte >= node.start_byte:
        raw = source[node.start_byte:body.start_byte].decode("utf-8", errors="replace").strip()
    else:
        raw = node_text(node, source).strip().splitlines()[0] if node_text(node, source).strip() else ""
    return raw.rstrip().rstrip("{").strip()


def parameter_container(node: Any):
    params = field_node(node, "parameters")
    if params is not None:
        return params
    for child in node.children:
        if child.type in {"formal_parameters", "parameters", "parameter_list"}:
            return child
    return None


def extract_parameter_types(node: Any, language: str, source: bytes) -> List[Dict[str, Any]]:
    container = parameter_container(node)
    if container is None:
        return []
    result = []
    valid_param_types = {
        "formal_parameter", "spread_parameter", "receiver_parameter",
        "typed_parameter", "typed_default_parameter", "default_parameter",
        "identifier", "list_splat_pattern", "dictionary_splat_pattern",
        "required_parameter", "optional_parameter", "assignment_pattern",
    }
    for child in container.named_children:
        raw = node_text(child, source).strip()
        if not raw or child.type not in valid_param_types:
            # Retain unknown parameter-shaped nodes conservatively, but skip comments.
            if not raw or child.type in {"comment", "line_comment", "block_comment"}:
                continue
        name_node = field_node(child, "name")
        type_node = field_node(child, "type")
        name = node_text(name_node, source).strip() if name_node is not None else ""
        type_text = node_text(type_node, source).strip() if type_node is not None else ""

        if not name:
            if language == "python":
                match = re.match(r"\*{0,2}\s*([A-Za-z_]\w*)", raw)
                name = match.group(1) if match else raw.split(":", 1)[0].split("=", 1)[0].strip()
                if not type_text and ":" in raw:
                    type_text = raw.split(":", 1)[1].split("=", 1)[0].strip()
            elif language == "javascript":
                match = re.match(r"(?:\.\.\.)?\s*([A-Za-z_$][\w$]*)", raw)
                name = match.group(1) if match else raw
                if not type_text and ":" in raw:
                    type_text = raw.split(":", 1)[1].split("=", 1)[0].strip()
            else:
                # Java declarations normally expose name/type fields; fallback to the final identifier.
                identifiers = re.findall(r"[A-Za-z_$][\w$]*", raw.split("=", 1)[0])
                name = identifiers[-1] if identifiers else raw
                if not type_text and len(identifiers) >= 2:
                    type_text = raw[:raw.rfind(name)].strip()

        if language == "python" and not type_text and ":" in raw:
            type_text = raw.split(":", 1)[1].split("=", 1)[0].strip()
        elif language == "javascript" and not type_text and ":" in raw:
            type_text = raw.split(":", 1)[1].split("=", 1)[0].strip()

        result.append({"name": name, "type": type_text or None, "declaration": raw})
    return result


def extract_return_type(node: Any, language: str, source: bytes) -> Optional[str]:
    field_names = {
        "python": ("return_type",),
        "java": ("type",),
        "javascript": ("return_type", "type"),
    }[language]
    for field_name in field_names:
        child = field_node(node, field_name)
        if child is not None:
            text = node_text(child, source).strip()
            if text:
                # For Java constructors the method grammar should have no return type.
                return text
    return None


def is_test_function(path: str, name: str, code: str, language: str, class_name: str) -> Tuple[bool, str]:
    p = "/" + path.lower().replace("\\", "/").strip("/") + "/"
    base = path.lower().rsplit("/", 1)[-1]
    if language == "python":
        if name.startswith("test_"):
            return True, "python_test_function_name"
        if class_name.split(".")[-1].startswith("Test") and name.startswith("test"):
            return True, "python_test_class_and_method_name"
        if "/tests/" in p or "/test/" in p:
            if name.startswith(("test", "check_")):
                return True, "test_path_and_function_name"
    elif language == "java":
        if re.search(r"@(?:org\.junit\.)?(?:Test|ParameterizedTest|RepeatedTest|TestFactory|TestTemplate)\b", code):
            return True, "java_test_annotation"
        if re.search(r"(?:^|/)[^/]*Tests?\.java$", path.lower()) and name.lower().startswith("test"):
            return True, "java_test_filename_and_method_name"
    else:
        if name.startswith("test_case::") or name.startswith("test_case@"):
            return True, "javascript_test_or_it_callback"
        filename_test = bool(re.search(r"(?:\.test|\.spec)\.[cm]?jsx?$", base)) or "/__tests__/" in p
        if filename_test and re.match(r"^(?:test|it|fit|xit|specify)(?:\b|_)", name):
            return True, "javascript_test_filename_and_function_name"
    return False, ""


def extract_imports(root_node: Any, language: str, source: bytes) -> List[str]:
    allowed = {
        "python": {"import_statement", "import_from_statement"},
        "java": {"import_declaration"},
        "javascript": {"import_statement"},
    }[language]
    imports = [
        node_text(node, source).strip()
        for node in root_node.named_children
        if node.type in allowed
    ]
    if language == "javascript":
        # CommonJS imports appear in top-level declarations.
        imports.extend(
            node_text(node, source).strip()
            for node in root_node.named_children
            if node.type in {"lexical_declaration", "variable_declaration"}
            and "require(" in node_text(node, source)
        )
    return list(dict.fromkeys(x for x in imports if x))


def extract_function_imports(root_node: Any, language: str, source: bytes,
                             node_to_id: Dict[Tuple[str, int, int, str], str],
                             path: str) -> Dict[str, List[str]]:
    """Collect imports/requires under the function whose scope owns them."""
    allowed = IMPORT_TYPES[language]
    result: Dict[str, List[str]] = defaultdict(list)
    for node in walk(root_node):
        is_import = node.type in allowed
        is_require = (
            language == "javascript"
            and node.type in {"lexical_declaration", "variable_declaration"}
            and "require(" in node_text(node, source)
        )
        if not (is_import or is_require):
            continue
        owner = nearest_function_node(node, language)
        if owner is None:
            continue
        owner_id = node_to_id.get(node_key(path, owner))
        text = node_text(node, source).strip()
        if owner_id and text and text not in result[owner_id]:
            result[owner_id].append(text)
    return result


def import_bindings(statement: str, language: str) -> Tuple[Set[str], bool]:
    text = statement.strip().rstrip(";")
    if language == "python":
        match = re.match(r"from\s+.+?\s+import\s+(.+)$", text)
        if match:
            names = set()
            for item in match.group(1).strip().strip("()").split(","):
                item = item.strip()
                if item == "*":
                    return set(), True
                if item:
                    names.add(item.split(" as ")[-1].strip())
            return names, False
        match = re.match(r"import\s+(.+)$", text)
        if match:
            names = set()
            for item in match.group(1).split(","):
                item = item.strip()
                if item:
                    names.add(item.split(" as ")[-1].split(".")[0].strip())
            return names, False
    elif language == "java":
        if text.startswith("import "):
            value = text[len("import "):].removeprefix("static ").strip()
            if value.endswith(".*"):
                return set(), True
            return {value.rsplit(".", 1)[-1]}, False
    else:
        if "require(" in text:
            match = re.match(r"(?:const|let|var)\s+([^=]+)=", text)
            if not match:
                return set(), False
            binding = match.group(1).strip()
            if binding.startswith("{") and binding.endswith("}"):
                names = set()
                for item in binding[1:-1].split(","):
                    item = item.strip()
                    if item:
                        names.add(re.split(r"\s*:\s*", item, maxsplit=1)[-1].strip())
                return names, False
            return {binding}, False
        match = re.match(r"import\s+(.+?)\s+from\s+", text)
        if match:
            clause = match.group(1).strip()
            names = set()
            # default import
            first = clause.split(",", 1)[0].strip()
            if first and not first.startswith("{") and first != "* as":
                names.add(first)
            for item in re.findall(r"\b([A-Za-z_$][\w$]*)\s+as\s+([A-Za-z_$][\w$]*)\b", clause):
                names.add(item[1])
            named_match = re.search(r"\{([^}]*)\}", clause, flags=re.S)
            if named_match:
                for item in named_match.group(1).split(","):
                    item = item.strip()
                    if item:
                        names.add(item.split(" as ")[-1].strip())
            if clause.startswith("* as "):
                names.add(clause[5:].strip())
            return names, False
    return set(), False


def filter_imports(imports: List[str], language: str, evidence_text: str) -> List[str]:
    kept = []
    for statement in imports:
        bindings, conservative = import_bindings(statement, language)
        if conservative or any(
            re.search(r"\b" + re.escape(name) + r"\b", evidence_text) for name in bindings
        ):
            kept.append(statement)
    return list(dict.fromkeys(kept))


def _without_source_extension(path: str) -> str:
    """Remove a recognized source suffix while preserving the relative path."""
    value = path.replace("\\", "/").strip("/")
    suffix = Path(value).suffix.lower()
    if suffix in LANG_BY_EXT:
        value = value[:-len(suffix)]
    return value


def _path_module_candidates(path: str, language: str) -> Set[str]:
    """Build plausible dotted module/type names from a repository-relative path."""
    value = _without_source_extension(path)
    parts = [part for part in value.split("/") if part]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return set()

    # Java source roots commonly include src/main/java or src/test/java.
    # All suffixes with at least two components let package-qualified imports
    # match even when a repository has an extra top-level directory.
    candidates: Set[str] = set()
    min_len = 2 if len(parts) > 1 else 1
    for start in range(0, len(parts) - min_len + 1):
        candidates.add(".".join(parts[start:]))

    if language == "java":
        # A function may live in an inner class whose name differs from the file.
        stem = parts[-1]
        # Package paths can be inferred from the source path after common roots.
        package_paths = set()
        for index, part in enumerate(parts[:-1]):
            if part in {"java", "kotlin", "scala"} and index + 1 < len(parts) - 1:
                package_paths.add(".".join(parts[index + 1:-1]))
        for package_path in package_paths:
            candidates.add(package_path + "." + stem)
    return {candidate.strip(".") for candidate in candidates if candidate.strip(".")}


def _java_package_candidates(path: str) -> Set[str]:
    parts = [part for part in path.replace("\\", "/").strip("/").split("/") if part]
    packages: Set[str] = set()
    for index, part in enumerate(parts[:-1]):
        if part in {"java", "kotlin", "scala"}:
            packages.add(".".join(parts[index + 1:-1]))
    if not packages and len(parts) > 1:
        packages.add(".".join(parts[:-1]))
    return packages


def _python_import_matches_target(statement: str, source_path: str, target: "FunctionInfo") -> bool:
    target_module_candidates = _path_module_candidates(target.path, "python")
    target_stem = Path(_without_source_extension(target.path)).name
    target_symbols = {target.name, target_stem}
    if target.class_name:
        target_symbols.update(target.class_name.split("."))

    text = statement.strip()
    match = re.match(r"from\s+([.\w]+)\s+import\s+(.+)$", text, flags=re.S)
    if match:
        module = match.group(1).strip().lstrip(".")
        names = set()
        for item in match.group(2).strip().strip("()").split(","):
            item = item.strip()
            if not item or item == "*":
                continue
            names.add(item.split(" as ")[-1].strip())
        # Direct module import, or `from package import module_or_symbol`.
        if module and any(
            module == candidate or module.endswith("." + candidate)
            for candidate in target_module_candidates
        ):
            return True
        parent_candidates = _path_module_candidates(
            "/".join(_without_source_extension(target.path).split("/")[:-1] + ["__init__.py"]),
            "python",
        )
        if module and any(
            module == candidate or module.endswith("." + candidate)
            for candidate in parent_candidates
        ) and target_symbols.intersection(names):
            return True
        return False

    match = re.match(r"import\s+(.+)$", text, flags=re.S)
    if match:
        for item in match.group(1).split(","):
            module = item.strip().split(" as ")[0].strip()
            if module and any(
                module == candidate or module.endswith("." + candidate)
                for candidate in target_module_candidates
            ):
                return True
    return False


def _javascript_import_matches_target(statement: str, source_path: str, target: "FunctionInfo") -> bool:
    specifier_match = re.search(r"\bfrom\s*[\"']([^\"']+)[\"']", statement)
    if not specifier_match:
        specifier_match = re.search(r"require\s*\(\s*[\"']([^\"']+)[\"']\s*\)", statement)
    if not specifier_match:
        return False
    specifier = specifier_match.group(1).strip()
    target_no_ext = _without_source_extension(target.path)

    if specifier.startswith("."):
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source_path), specifier))
        candidates = {resolved, resolved + ".js", resolved + ".jsx", resolved + ".mjs", resolved + ".cjs"}
        candidates.update(posixpath.join(resolved, "index" + suffix) for suffix in (".js", ".jsx", ".mjs", ".cjs"))
        return target_no_ext in {_without_source_extension(item) for item in candidates}

    # Non-relative aliases (for example configured baseUrl paths) are less
    # certain, so compare package-style module names conservatively.
    module = specifier.removesuffix(".js").replace("/", ".").strip(".")
    target_candidates = _path_module_candidates(target.path, "javascript")
    return any(module == candidate or module.endswith("." + candidate) for candidate in target_candidates)


def _file_imports_target(source_path: str, imports: List[str], target: "FunctionInfo",
                         language: str) -> bool:
    """Check whether a source/test file explicitly imports the target module/class."""
    if language == "python":
        return any(_python_import_matches_target(item, source_path, target) for item in imports)

    if language == "javascript":
        return any(_javascript_import_matches_target(item, source_path, target) for item in imports)

    # Java: import declarations may refer to the top-level class, a nested class,
    # a static method, or a package wildcard. Same-package access is deliberately
    # handled separately because it does not require an import declaration.
    target_path_candidates = _path_module_candidates(target.path, "java")
    target_file_stem = Path(_without_source_extension(target.path)).name
    class_leaves = {target_file_stem}
    if target.class_name:
        class_leaves.update(target.class_name.split("."))
    target_packages = _java_package_candidates(target.path)
    for package in target_packages:
        for class_leaf in class_leaves:
            if package:
                target_path_candidates.add(package + "." + class_leaf)
            else:
                target_path_candidates.add(class_leaf)
    for statement in imports:
        match = re.match(r"import\s+(?:static\s+)?([A-Za-z_$][\w.$*]*)\s*;?", statement.strip())
        if not match:
            continue
        imported = match.group(1)
        if imported.endswith(".*"):
            package = imported[:-2]
            if (package in target_path_candidates or package in target_packages
                    or any(package.endswith("." + p) for p in target_packages if p)):
                return True
        elif any(imported == candidate or imported.startswith(candidate + ".")
                 for candidate in target_path_candidates):
            return True
        elif imported.rsplit(".", 1)[-1] in class_leaves and len(imported.split(".")) == 1:
            return True
    return False


def _java_package_name(source: str) -> str:
    """Return a Java package declaration, or an empty string for the default package."""
    match = re.search(r"(?m)^\s*package\s+([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*;", source)
    return match.group(1) if match else ""


def _java_code_without_comments_and_strings(source: str) -> str:
    """Reduce comment/string false positives when looking for Java class references."""
    # Retain newlines so that simple source-pattern checks remain predictable.
    pattern = re.compile(
        r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
        flags=re.S,
    )
    return pattern.sub(lambda m: "\n" * m.group(0).count("\n"), source)


def _java_test_references_target(source_path: str, imports: List[str], target: "FunctionInfo",
                                target_source: str, test_source: str) -> bool:
    """Recognize Java test references via imports, fully-qualified names, or same-package use.

    The caller function has already been required to contain a static invocation whose
    method name matches the target. This additional check prevents unrelated same-name
    tests from being included unless the test file also provides evidence that it refers
    to the target class.
    """
    if _file_imports_target(source_path, imports, target, "java"):
        return True

    target_package = _java_package_name(target_source)
    test_package = _java_package_name(test_source)
    file_stem = Path(_without_source_extension(target.path)).name
    class_names = {file_stem}
    if target.class_name:
        class_names.add(target.class_name)
        class_names.add(target.class_name.split(".")[-1])

    code = _java_code_without_comments_and_strings(test_source)
    # A fully-qualified class reference is valid even when there is no import and
    # the test belongs to another package.
    fully_qualified_names = set()
    if target_package:
        for name in class_names:
            fully_qualified_names.add(f"{target_package}.{name}")
    for name in sorted(fully_qualified_names, key=len, reverse=True):
        if re.search(r"(?<![\w$])" + re.escape(name) + r"(?![\w$])", code):
            return True

    # Package-private access means same-package tests do not need an import.
    # Still require an actual reference to the target class in source code, rather
    # than accepting every test in the same package.
    if test_package == target_package:
        for name in class_names:
            if re.search(r"(?<![\w$])" + re.escape(name) + r"(?![\w$])", code):
                return True
    return False


def get_parameters_node(node: Any):
    params = field_node(node, "parameters")
    if params is not None:
        return params
    for child in node.children:
        if child.type in {"formal_parameters", "parameters", "parameter_list"}:
            return child
    return None


def get_function_id(path: str, node: Any, name: str) -> str:
    return f"{path}:{int(node.start_byte)}:{int(node.end_byte)}:{node.type}:{name}"


@dataclass
class FunctionInfo:
    id: str
    path: str
    language: str
    name: str
    class_name: str
    qualified_name: str
    start_line: int
    end_line: int
    signature: str
    code: str
    docstring: str
    leading_comments: str
    parameter_types: List[Dict[str, Any]]
    return_type: Optional[str]
    is_test: bool
    test_reason: str
    is_constructor: bool = False
    is_default_export: bool = False


@dataclass
class CallSite:
    path: str
    language: str
    line: int
    end_line: int
    callee_name: str
    callee_expression: str
    caller_id: Optional[str]
    code: str
    syntax_kind: str


def get_called_name(call_node: Any, language: str, source: bytes) -> Tuple[str, str]:
    if language == "python":
        function_node = field_node(call_node, "function")
        expression = node_text(function_node, source).strip() if function_node is not None else ""
        match = re.search(r"([A-Za-z_]\w*)\s*$", expression)
        return (match.group(1) if match else expression), expression
    if language == "java":
        if call_node.type == "method_invocation":
            name = field_text(call_node, "name", source)
            obj = field_text(call_node, "object", source)
            return name or obj, f"{obj}.{name}" if obj else name
        if call_node.type == "object_creation_expression":
            typ = field_text(call_node, "type", source)
            base = typ.split("<", 1)[0].split(".")[-1].strip()
            return base, f"new {typ}".strip()
        if call_node.type == "explicit_constructor_invocation":
            text = node_text(call_node, source).strip()
            return ("this" if text.startswith("this") else "super"), text
    if language == "javascript":
        function_node = field_node(call_node, "function")
        if function_node is None and call_node.type == "new_expression":
            function_node = field_node(call_node, "constructor")
        expression = node_text(function_node, source).strip() if function_node is not None else ""
        match = re.search(r"([A-Za-z_$][\w$]*)\s*$", expression)
        return (match.group(1) if match else expression), expression
    return "", ""


def get_type_name(node: Any, source: bytes) -> str:
    name = field_text(node, "name", source) or direct_identifier(node, source)
    if name:
        return name
    text = node_text(node, source).strip()
    if text:
        match = re.search(r"(?:class|interface|enum|record|def|function)\s+([A-Za-z_$][\w$]*)", text)
        if match:
            return match.group(1)
    return ""


def extract_class_contexts(path: str, language: str, source: bytes, root: Any,
                           max_code_chars: int) -> List[Dict[str, Any]]:
    contexts = []
    for node in walk(root):
        if node.type not in CLASS_TYPES[language]:
            continue
        name = get_type_name(node, source)
        if not name:
            continue
        parent_name = nearest_class_name(node, language, source)
        qualified = f"{parent_name}.{name}" if parent_name else name
        fields: List[str] = []
        constructors: List[str] = []
        body = next((c for c in node.children if c.type in TYPE_BODY_TYPES[language]), None)
        if body is not None:
            for child in body.children:
                if language == "java":
                    if child.type == "field_declaration":
                        fields.append(node_text(child, source).strip())
                    elif child.type == "constructor_declaration":
                        constructors.append(node_text(child, source).strip())
                elif language == "javascript":
                    if child.type in {"field_definition", "public_field_definition"}:
                        fields.append(node_text(child, source).strip())
                    elif child.type == "method_definition" and field_text(child, "name", source) == "constructor":
                        constructors.append(node_text(child, source).strip())
                else:
                    if child.type == "decorated_definition":
                        inner = next((c for c in child.children if c.type == "function_definition"), None)
                        if inner is not None and field_text(inner, "name", source) == "__init__":
                            constructors.append(node_text(child, source).strip())
                    elif child.type == "function_definition" and field_text(child, "name", source) == "__init__":
                        constructors.append(node_text(child, source).strip())
                    elif child.type in {"assignment", "expression_statement", "annotated_assignment"}:
                        # Only assignments at class scope are recorded as class variables/fields.
                        raw = node_text(child, source).strip()
                        expression = next(iter(child.named_children), None)
                        is_annotated = (
                            child.type == "annotated_assignment"
                            or (expression is not None and expression.type == "annotated_assignment")
                            or (expression is not None and expression.type == "assignment" and ":" in raw)
                        )
                        if "=" in raw or is_annotated:
                            fields.append(raw)
        contexts.append({
            "file": path,
            "language": language,
            "name": name,
            "qualified_name": qualified,
            "kind": node.type,
            "start_line": point_row(node.start_point) + 1,
            "end_line": point_row(node.end_point) + 1,
            "constructors": [trim_code(x, max_code_chars) for x in constructors],
            "fields": [trim_code(x, max_code_chars) for x in fields],
            "code": trim_code(node_text(node, source), max_code_chars),
        })
    return contexts


def trim_code(code: str, max_chars: int) -> str:
    if len(code) <= max_chars:
        return code
    return code[:max_chars] + "\n... [truncated by --max-code-chars] ..."


def collect_functions(path: str, language: str, source: bytes, root: Any,
                      max_code_chars: int) -> Tuple[List[FunctionInfo], Dict[Tuple[str, int, int, str], str]]:
    functions: List[FunctionInfo] = []
    node_to_id: Dict[Tuple[str, int, int, str], str] = {}
    for node in walk(root):
        if node.type not in FUNCTION_TYPES[language]:
            continue
        name = callable_name(node, language, source)
        class_name = nearest_class_name(node, language, source)
        outer = nearest_function_node(node, language)
        prefix = ""
        if outer is not None:
            prefix = callable_name(outer, language, source) + "."
        qualified_name = f"{class_name}.{name}" if class_name else f"{prefix}{name}"
        full_node = declaration_full_node(node, language)
        code_raw = node_text(full_node, source)
        start_line = point_row(full_node.start_point) + 1
        end_line = point_row(full_node.end_point) + 1
        comments = leading_comments(source, point_row(full_node.start_point))
        docstring = extract_python_docstring(node, source) if language == "python" else ""
        test_name, test_reason = is_test_function(path, name, code_raw, language, class_name)
        if language == "javascript" and name.startswith("test_case::"):
            test_name, test_reason = True, "javascript_test_or_it_callback"
        is_default_export = False
        if language == "javascript" and (not class_name or name == "constructor"):
            current = node
            while current is not None and current.type != "program":
                if current.type == "export_statement":
                    is_default_export = bool(re.match(
                        r"\s*export\s+default\b", node_text(current, source)
                    ))
                    break
                current = current.parent
        info = FunctionInfo(
            id=get_function_id(path, node, name),
            path=path,
            language=language,
            name=name,
            class_name=class_name,
            qualified_name=qualified_name,
            start_line=start_line,
            end_line=end_line,
            signature=trim_code(get_callable_signature(node, language, source), min(max_code_chars, 3000)),
            code=trim_code(code_raw, max_code_chars),
            docstring=docstring,
            leading_comments=comments,
            parameter_types=extract_parameter_types(node, language, source),
            return_type=extract_return_type(node, language, source),
            is_test=test_name,
            test_reason=test_reason,
            is_constructor=(language == "java" and node.type == "constructor_declaration")
                          or (language == "javascript" and name == "constructor")
                          or (language == "python" and name == "__init__"),
            is_default_export=is_default_export,
        )
        functions.append(info)
        node_to_id[node_key(path, node)] = info.id
    return functions, node_to_id


def collect_calls(path: str, language: str, source: bytes, root: Any,
                  node_to_id: Dict[Tuple[str, int, int, str], str],
                  max_code_chars: int) -> List[CallSite]:
    calls = []
    for node in walk(root):
        if node.type not in CALL_TYPES[language]:
            continue
        name, expression = get_called_name(node, language, source)
        if not name:
            continue
        caller_node = nearest_function_node(node, language)
        caller_id = node_to_id.get(node_key(path, caller_node)) if caller_node is not None else None
        calls.append(CallSite(
            path=path,
            language=language,
            line=point_row(node.start_point) + 1,
            end_line=point_row(node.end_point) + 1,
            callee_name=name,
            callee_expression=expression,
            caller_id=caller_id,
            code=trim_code(node_text(node, source), max_code_chars),
            syntax_kind=node.type,
        ))
    return calls


def scan_repository(repo: Path, max_file_bytes: int = 2_000_000,
                    allowed_files: Optional[Iterable[str]] = None,
                    max_code_chars: int = 12000) -> Dict[str, Any]:
    """Parse each project source file once; retain only compact code records, not ASTs."""
    root_path = repo.resolve()
    allowed = None
    if allowed_files is not None:
        allowed = {Path(p).as_posix().removeprefix("./") for p in allowed_files}
    functions: List[FunctionInfo] = []
    calls: List[CallSite] = []
    classes: List[Dict[str, Any]] = []
    imports_by_file: Dict[str, List[str]] = {}
    imports_by_function: Dict[str, List[str]] = {}
    skipped: List[str] = []
    scan_started = time.monotonic()
    source_files_seen = 0
    files_parsed = 0

    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = sorted(d for d in dirnames if d.lower() not in DEFAULT_EXCLUDED_DIRS)
        for filename in sorted(filenames):
            path_obj = Path(dirpath) / filename
            language = LANG_BY_EXT.get(path_obj.suffix.lower())
            if not language:
                continue
            source_files_seen += 1
            if source_files_seen == 1 or source_files_seen % 250 == 0:
                elapsed = time.monotonic() - scan_started
                print(
                    f"[索引扫描] 已发现源文件 {source_files_seen}，已解析 {files_parsed}，"
                    f"函数/调用点累计 {len(functions)}/{len(calls)}，耗时 {elapsed:.1f}s",
                    flush=True,
                )
            rel = path_obj.resolve().relative_to(root_path).as_posix()
            if allowed is not None and rel not in allowed:
                continue
            try:
                size = path_obj.stat().st_size
                if size > max_file_bytes:
                    skipped.append(f"{rel}: file exceeds {max_file_bytes} bytes")
                    continue
                source = path_obj.read_bytes()
                tree = get_parser(language).parse(source)
            except (OSError, UnicodeError, ValueError) as exc:
                skipped.append(f"{rel}: read/parse error: {exc}")
                continue

            root = tree.root_node
            imports_by_file[rel] = extract_imports(root, language, source)
            local_functions, node_to_id = collect_functions(rel, language, source, root, max_code_chars)
            imports_by_function.update(
                extract_function_imports(root, language, source, node_to_id, rel)
            )
            local_calls = collect_calls(rel, language, source, root, node_to_id, max_code_chars=2500)
            local_classes = extract_class_contexts(rel, language, source, root, max_code_chars)
            functions.extend(local_functions)
            calls.extend(local_calls)
            classes.extend(local_classes)
            files_parsed += 1
            if files_parsed % 250 == 0:
                elapsed = time.monotonic() - scan_started
                print(
                    f"[索引扫描] 已解析 {files_parsed} 个源文件；"
                    f"函数/调用点 {len(functions)}/{len(calls)}；耗时 {elapsed:.1f}s",
                    flush=True,
                )
            # tree/source go out of scope here to avoid retaining thousands of full parse trees.

    scan_elapsed = time.monotonic() - scan_started
    print(
        f"[索引扫描] 完成：解析源文件 {files_parsed}/{source_files_seen}，"
        f"函数/调用点 {len(functions)}/{len(calls)}，耗时 {scan_elapsed:.1f}s",
        flush=True,
    )

    functions_by_id = {f.id: f for f in functions}
    by_name: Dict[Tuple[str, str], List[FunctionInfo]] = defaultdict(list)
    caller_calls: Dict[str, List[CallSite]] = defaultdict(list)
    calls_by_name: Dict[Tuple[str, str], List[CallSite]] = defaultdict(list)
    calls_by_path_name: Dict[Tuple[str, str, str], List[CallSite]] = defaultdict(list)
    paths_with_calls_by_language: Dict[str, Set[str]] = defaultdict(set)
    for info in functions:
        by_name[(info.language, info.name)].append(info)
    for call in calls:
        calls_by_name[(call.language, call.callee_name)].append(call)
        calls_by_path_name[(call.path, call.language, call.callee_name)].append(call)
        paths_with_calls_by_language[call.language].add(call.path)
        if call.caller_id:
            caller_calls[call.caller_id].append(call)

    outgoing_expressions: Dict[str, Set[Tuple[str, str]]] = defaultdict(set)
    for call in calls:
        if call.caller_id:
            outgoing_expressions[call.caller_id].add((call.language, call.callee_expression or call.callee_name))

    type_by_name: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for type_info in classes:
        type_by_name[(type_info["language"], type_info["name"])].append(type_info)

    # Inverted import-token index avoids scanning every import in every target pass.
    import_paths_by_identifier: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    all_imports_by_file: Dict[str, List[str]] = {
        path: list(statements) for path, statements in imports_by_file.items()
    }
    for function_id, statements in imports_by_function.items():
        function = functions_by_id.get(function_id)
        if function is None:
            continue
        combined = all_imports_by_file.setdefault(function.path, [])
        combined.extend(statement for statement in statements if statement not in combined)

    for import_path, statements in all_imports_by_file.items():
        import_language = LANG_BY_EXT.get(Path(import_path).suffix.lower())
        if not import_language:
            continue
        for statement in statements:
            for token in re.findall(r"[A-Za-z_$][\w$]*", statement):
                import_paths_by_identifier[(import_language, token)].add(import_path)

    return {
        "repo": root_path,
        "max_file_bytes": max_file_bytes,
        "functions": functions,
        "functions_by_id": functions_by_id,
        "by_name": by_name,
        "calls": calls,
        "calls_by_name": calls_by_name,
        "calls_by_path_name": calls_by_path_name,
        "paths_with_calls_by_language": paths_with_calls_by_language,
        "import_paths_by_identifier": import_paths_by_identifier,
        "caller_calls": caller_calls,
        "outgoing_degree": {key: len(outgoing_expressions.get(key, set())) for key in functions_by_id},
        "classes": classes,
        "type_by_name": type_by_name,
        "imports_by_file": imports_by_file,
        "imports_by_function": imports_by_function,
        "all_imports_by_file": all_imports_by_file,
        "skipped": skipped,
    }


def function_to_dict(info: FunctionInfo) -> Dict[str, Any]:
    return {
        "id": info.id,
        "file": info.path,
        "language": info.language,
        "name": info.name,
        "qualified_name": info.qualified_name,
        "class_name": info.class_name or None,
        "start_line": info.start_line,
        "end_line": info.end_line,
        "signature": info.signature,
        "code": info.code,
        "docstring": info.docstring or None,
        "leading_comments": info.leading_comments or None,
        "parameter_types": info.parameter_types,
        "return_type": info.return_type,
        "is_test_candidate": info.is_test,
        "test_classification_reason": info.test_reason or None,
    }


def call_to_dict(call: CallSite) -> Dict[str, Any]:
    return {
        "file": call.path,
        "line": call.line,
        "end_line": call.end_line,
        "callee_name": call.callee_name,
        "callee_expression": call.callee_expression,
        "call_expression": call.code,
        "syntax_kind": call.syntax_kind,
        "relation_evidence": "static callee-name match; not runtime-confirmed",
    }


def normalise_target_path(repo: Path, record_path: str) -> str:
    path = Path(record_path)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(repo.resolve()).as_posix()
        except ValueError:
            return path.as_posix()
    return path.as_posix().removeprefix("./")


def match_target(record: Dict[str, Any], index: Dict[str, Any]) -> FunctionInfo:
    repo = index["repo"]
    raw_path = record.get("src_file") or record.get("file") or record.get("target_file")
    name = record.get("name") or record.get("target_name")
    if not raw_path or not name:
        raise ValueError("Function record must contain src_file/file and name/target_name")
    relpath = normalise_target_path(repo, str(raw_path))
    wanted_class = str(record.get("class_name") or record.get("target_class") or "").split(".")[-1]
    wanted_line = record.get("start_line") or record.get("target_line")

    candidates = [f for f in index["functions"] if f.path == relpath and f.name == str(name)]
    if wanted_class:
        by_class = [f for f in candidates if f.class_name.split(".")[-1] == wanted_class]
        if by_class:
            candidates = by_class
    if wanted_line is not None:
        by_line = [f for f in candidates if f.start_line == int(wanted_line)]
        if by_line:
            candidates = by_line
        else:
            # Decorators/wrappers can shift the recorded start line slightly; try an enclosing range.
            by_line = [f for f in candidates if f.start_line <= int(wanted_line) <= f.end_line]
            if by_line:
                candidates = by_line
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        same_named = [f for f in index["functions"] if f.name == str(name)]
        hints = "\n".join(f"  {x.path}:{x.start_line} {x.qualified_name}" for x in same_named[:12])
        raise ValueError(f"Cannot find function {name!r} in {relpath!r}. Same-name definitions:\n{hints}")
    details = "\n".join(f"  {x.path}:{x.start_line}-{x.end_line} {x.qualified_name}" for x in candidates)
    raise ValueError(f"Target is ambiguous; add class_name/start_line. Candidates:\n{details}")


def find_class_context(target: FunctionInfo, classes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not target.class_name:
        return None
    leaf = target.class_name.split(".")[-1]
    candidates = [c for c in classes if c["file"] == target.path and c["name"] == leaf
                  and c["start_line"] <= target.start_line <= c["end_line"]]
    if not candidates:
        candidates = [c for c in classes if c["file"] == target.path and c["name"] == leaf]
    if not candidates:
        return {"name": leaf, "file": target.path, "constructors": [], "fields": []}
    selected = min(candidates, key=lambda c: c["end_line"] - c["start_line"])
    # Only expose the requested second-priority pieces, not the whole class body.
    return {
        "name": selected["name"],
        "qualified_name": selected["qualified_name"],
        "file": selected["file"],
        "kind": selected["kind"],
        "start_line": selected["start_line"],
        "end_line": selected["end_line"],
        "constructors": selected["constructors"],
        "fields": selected["fields"],
    }


def relevant_type_definitions(index: Dict[str, Any], target: FunctionInfo,
                               evidence_text: str, max_types: int) -> List[Dict[str, Any]]:
    if max_types <= 0:
        return []
    result = []
    seen = set()
    # Restrict type context to declarations explicitly present in the target's
    # parameter/return annotations. Searching every capitalized token in related
    # code produced large amounts of weak, same-name context in big repositories.
    explicit_type_text = " ".join(
        [str(p.get("type") or "") for p in target.parameter_types] + [str(target.return_type or "")]
    )
    explicit_names = set(re.findall(r"\b[A-Za-z_$][\w$]*\b", explicit_type_text))
    keys = [
        key for key in index["type_by_name"].keys()
        if key[0] == target.language and key[1] in explicit_names
    ]
    keys.sort(key=lambda key: key[1])
    for language, type_name in keys:
        declarations = index["type_by_name"][(language, type_name)]
        same_file = [item for item in declarations if item["file"] == target.path]
        # A same-file declaration is lexically relevant. Across files, include a
        # declaration only when the type name is unique repository-wide; otherwise
        # static name matching cannot safely choose an implementation.
        selected = same_file or (declarations if len(declarations) == 1 else [])
        for declaration in selected:
            if declaration["file"] == target.path and declaration["name"] == target.class_name.split(".")[-1]:
                continue  # target's own class is separately represented by class_context
            identity = (declaration["file"], declaration["name"], declaration["start_line"])
            if identity in seen:
                continue
            seen.add(identity)
            result.append({
                "name": declaration["name"],
                "qualified_name": declaration["qualified_name"],
                "language": declaration["language"],
                "file": declaration["file"],
                "kind": declaration["kind"],
                "start_line": declaration["start_line"],
                "end_line": declaration["end_line"],
                "code": declaration["code"],
                "relation_evidence": "type appears explicitly in target parameter/return annotations",
            })
            if len(result) >= max_types:
                return result
    return result


def _source_record(path: str, code: str) -> Dict[str, str]:
    """Keep each context fragment intentionally minimal: source file + code only."""
    code = (code or "").strip()
    if not code:
        return {"file": path, "code": ""}
    return {"file": path, "code": code}


def _function_source(info: FunctionInfo) -> str:
    """Return the function source together with its immediately preceding docs/comments."""
    parts = []
    if info.leading_comments:
        parts.append(info.leading_comments.strip())
    code = (info.code or "").strip()
    if code:
        # Avoid duplicating comments if the parser's declaration node already includes them.
        if not parts or parts[0] not in code:
            parts.append(code)
    return "\n".join(part for part in parts if part).strip()



def _read_source_text(index: Dict[str, Any], path: str) -> str:
    """Read a source file lazily and cache it only if a resolver needs it."""
    cache = index.setdefault("_source_text_cache", {})
    if path not in cache:
        try:
            cache[path] = (Path(index["repo"]) / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            cache[path] = ""
    return cache[path]


def _visible_imports(index: Dict[str, Any], path: str,
                     function_id: Optional[str] = None,
                     include_all_scopes: bool = False) -> List[str]:
    """Return imports visible to one function, or all imports for candidate discovery."""
    if include_all_scopes:
        return list(index.get("all_imports_by_file", {}).get(path, []))
    imports = list(index["imports_by_file"].get(path, []))
    if function_id:
        for statement in index.get("imports_by_function", {}).get(function_id, []):
            if statement not in imports:
                imports.append(statement)
    return imports


def _import_alias_pairs(statement: str, language: str) -> List[Tuple[str, str]]:
    """Return (original imported name, local alias) pairs for explicit symbol imports."""
    text = statement.strip().rstrip(";")
    pairs: List[Tuple[str, str]] = []
    if language == "python":
        match = re.match(r"from\s+[.\w]+\s+import\s+(.+)$", text, flags=re.S)
        if not match:
            return pairs
        raw = match.group(1).strip().strip("()")
        for item in raw.split(","):
            item = item.strip()
            if not item or item == "*":
                continue
            bits = re.split(r"\s+as\s+", item)
            original = bits[0].strip()
            alias = bits[-1].strip()
            if original and alias:
                pairs.append((original, alias))
    elif language == "javascript":
        default_match = re.match(
            r"import\s+([A-Za-z_$][\w$]*)\s*(?:,|\s+from\b)", text
        )
        if default_match:
            pairs.append(("default", default_match.group(1)))
        match = re.search(r"\{([^}]*)\}\s*from\s*[\"'][^\"']+[\"']", text, flags=re.S)
        if match:
            for item in match.group(1).split(","):
                item = item.strip()
                if not item:
                    continue
                bits = re.split(r"\s+as\s+", item)
                original, alias = bits[0].strip(), bits[-1].strip()
                if original and alias:
                    pairs.append((original, alias))
        destructured_require = re.match(
            r"(?:const|let|var)\s*\{([^}]*)\}\s*=\s*require\s*\(", text,
            flags=re.S,
        )
        if destructured_require:
            for item in destructured_require.group(1).split(","):
                item = item.strip()
                if not item:
                    continue
                bits = re.split(r"\s*:\s*", item, maxsplit=1)
                original, alias = bits[0].strip(), bits[-1].strip()
                if original and alias:
                    pairs.append((original, alias))
    return pairs


def _imported_aliases_for_definition(source_path: str, definition: FunctionInfo,
                                     index: Dict[str, Any],
                                     function_id: Optional[str] = None,
                                     include_all_scopes: bool = False) -> Set[str]:
    """Find local aliases explicitly bound to a function/class in a candidate file."""
    cache = index.setdefault("_definition_alias_cache", {})
    cache_key = (source_path, definition.id, function_id, include_all_scopes)
    if cache_key in cache:
        return set(cache[cache_key])
    imports = _visible_imports(
        index, source_path, function_id, include_all_scopes=include_all_scopes
    )
    symbols = {definition.name}
    if definition.class_name:
        symbols.add(definition.class_name.split(".")[-1])
    aliases: Set[str] = set()
    for statement in imports:
        if not _file_imports_target(source_path, [statement], definition, definition.language):
            continue
        for original, alias in _import_alias_pairs(statement, definition.language):
            if (original in symbols
                    or (definition.language == "javascript" and original == "default"
                        and definition.is_default_export)):
                aliases.add(alias)
    cache[cache_key] = set(aliases)
    return aliases


def _import_alias_originals(imports: List[str], language: str) -> Dict[str, Set[str]]:
    """Map imported local aliases back to original names, for candidate lookup."""
    result: Dict[str, Set[str]] = defaultdict(set)
    for statement in imports:
        for original, alias in _import_alias_pairs(statement, language):
            result[alias].add(original)
    return result

def _imported_module_aliases_for_definition(source_path: str, definition: FunctionInfo,
                                            index: Dict[str, Any],
                                            function_id: Optional[str] = None) -> Set[str]:
    """Find imported module/namespace qualifiers that can lead to a definition."""
    imports = _visible_imports(index, source_path, function_id)
    aliases: Set[str] = set()
    for statement in imports:
        text = statement.strip().rstrip(";")
        if definition.language == "python":
            match = re.match(r"import\s+(.+)$", text, flags=re.S)
            if not match:
                continue
            for item in match.group(1).split(","):
                item = item.strip()
                if not item:
                    continue
                bits = re.split(r"\s+as\s+", item)
                module, local_alias = bits[0].strip(), bits[-1].strip()
                if _python_import_matches_target("import " + item, source_path, definition):
                    aliases.add(local_alias if len(bits) > 1 else module)
                    if len(bits) == 1:
                        aliases.add(module.split(".")[0])
        elif definition.language == "javascript":
            if not _javascript_import_matches_target(text, source_path, definition):
                continue
            match = re.search(r"\*\s+as\s+([A-Za-z_$][\w$]*)\s+from", text)
            if match:
                aliases.add(match.group(1))
            match = re.match(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*require\s*\(", text)
            if match:
                aliases.add(match.group(1))
    return aliases


def _function_class_leaf(info: FunctionInfo) -> str:
    return info.class_name.split(".")[-1] if info.class_name else ""


def _java_same_package(path_a: str, path_b: str, index: Dict[str, Any]) -> bool:
    if Path(path_a).suffix.lower() != ".java" or Path(path_b).suffix.lower() != ".java":
        return False
    source_a = _read_source_text(index, path_a)
    source_b = _read_source_text(index, path_b)
    return _java_package_name(source_a) == _java_package_name(source_b)


def _class_names_and_aliases(path: str, definition: FunctionInfo,
                             index: Dict[str, Any],
                             function_id: Optional[str] = None,
                             include_all_scopes: bool = False) -> Set[str]:
    names = set()
    class_leaf = _function_class_leaf(definition)
    if class_leaf:
        names.add(class_leaf)
        names.add(definition.class_name)
    elif definition.is_constructor:
        names.add(definition.name)
    # JavaScript/Python constructors can be represented as ordinary class members;
    # the source file stem is only a secondary hint, never sufficient by itself.
    names.update(_imported_aliases_for_definition(
        path, definition, index, function_id,
        include_all_scopes=include_all_scopes,
    ))
    return {name for name in names if name}


def _receiver_matches_definition(call: CallSite, caller: FunctionInfo,
                                definition: FunctionInfo, source_text: str,
                                index: Dict[str, Any]) -> bool:
    """Conservatively check whether a method receiver can denote definition's class."""
    expression = (call.callee_expression or "").strip()
    if "." not in expression:
        return False
    receiver = expression.rsplit(".", 1)[0].strip()
    if not receiver:
        return False

    candidate_class = _function_class_leaf(definition)
    if not candidate_class:
        return False
    class_names = _class_names_and_aliases(call.path, definition, index, caller.id)
    if candidate_class:
        class_names.add(candidate_class)
    # `this`/`self` establishes a receiver only within the same class definition.
    if receiver in {"self", "this", "cls"}:
        return (caller.path == definition.path
                and caller.class_name == definition.class_name
                and bool(caller.class_name))

    # Direct static calls or expressions such as `new Type().method()`.
    receiver_clean = receiver.replace(" ", "")
    if receiver_clean in class_names:
        return True
    type_match = re.search(r"(?:new\s+)?([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(?\s*\)?$", receiver)
    if type_match:
        type_name = type_match.group(1)
        if type_name in class_names or type_name.split(".")[-1] in class_names:
            return True

    # Infer a variable's type only from an explicit annotation/declaration or a
    # direct constructor assignment in this file; do not guess from variable names.
    code = _java_code_without_comments_and_strings(source_text)
    language = definition.language
    for type_name in class_names:
        escaped_type = re.escape(type_name)
        escaped_receiver = re.escape(receiver)
        if language == "python":
            patterns = [
                rf"\b{escaped_receiver}\s*:\s*(?:[\w.]+\.)?{escaped_type}\b",
                rf"\b{escaped_receiver}\s*=\s*{escaped_type}\s*\(",
            ]
        elif language == "java":
            patterns = [
                rf"\b{escaped_type}\s+{escaped_receiver}\b",
                rf"\b{escaped_receiver}\s*=\s*new\s+{escaped_type}\s*\(",
            ]
        else:
            patterns = [
                rf"\b(?:const|let|var)\s+{escaped_receiver}\s*=\s*new\s+{escaped_type}\s*\(",
                rf"\b{escaped_receiver}\s*:\s*{escaped_type}\b",
            ]
        if any(re.search(pattern, code) for pattern in patterns):
            return True
    return False


def _receiver_scope_text(caller: FunctionInfo, index: Dict[str, Any]) -> str:
    """Limit receiver-type inference to the caller and its declaring class fields."""
    parts = [_function_source(caller)]
    class_context = find_class_context(caller, index["classes"])
    if class_context:
        parts.extend(class_context.get("fields", []))
    return "\n".join(part for part in parts if part)


def _is_java_static_import_of_method(path: str, definition: FunctionInfo,
                                     index: Dict[str, Any]) -> bool:
    if definition.language != "java" or not definition.class_name:
        return False
    imports = index["imports_by_file"].get(path, [])
    owner = definition.class_name.replace("$", ".")
    owner_leaf = definition.class_name.split(".")[-1]
    for statement in imports:
        match = re.match(r"import\s+static\s+([\w.$]+)\s*;?", statement.strip())
        if not match:
            continue
        imported = match.group(1)
        if imported.rsplit(".", 1)[-1] != definition.name:
            continue
        owner_from_import = imported.rsplit(".", 1)[0]
        if owner_from_import == owner or owner_from_import.endswith("." + owner_leaf):
            return True
    return False



def _argument_count(call: CallSite) -> Optional[int]:
    """Count top-level call arguments approximately without evaluating expressions."""
    code = (call.code or "").strip()
    start = code.find("(")
    if start < 0:
        return None
    depth = 0
    commas = 0
    has_content = False
    quote = None
    escaped = False
    for char in code[start:]:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"', "`"}:
            quote = char
            has_content = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return 0 if not has_content else commas + 1
        elif depth == 1 and char == ",":
            commas += 1
        elif depth == 1 and not char.isspace():
            has_content = True
    return None


def _narrow_by_arity(call: CallSite, candidates: List[FunctionInfo]) -> List[FunctionInfo]:
    """Disambiguate overloads by argument count; leave unresolved overloads unselected."""
    unique = {candidate.id: candidate for candidate in candidates}
    values = list(unique.values())
    if len(values) <= 1:
        return values
    actual = _argument_count(call)
    if actual is None:
        return []
    exact = [candidate for candidate in values if len(candidate.parameter_types) == actual]
    return exact if len(exact) == 1 else []


def _call_resolves_to_definition(call: CallSite, caller: FunctionInfo,
                                 definition: FunctionInfo, index: Dict[str, Any]) -> bool:
    """Resolve a call site to one specific static definition using scope and imports."""
    if call.language != definition.language or caller.language != definition.language:
        return False
    lang = definition.language
    class_leaf = _function_class_leaf(definition)
    call_names = {definition.name}
    # Import aliases matter for directly imported functions and constructor classes.
    if not definition.class_name or definition.is_constructor:
        call_names.update(_imported_aliases_for_definition(
            call.path, definition, index, caller.id
        ))
        if definition.is_constructor and class_leaf:
            call_names.add(class_leaf)
    if call.callee_name not in call_names:
        return False

    # Constructor calls resolve against a class constructor, not arbitrary methods
    # that happen to share the class name.
    is_creation = call.syntax_kind in {"object_creation_expression", "new_expression"}
    if (lang == "python" and definition.is_constructor
            and call.callee_name in _class_names_and_aliases(
                call.path, definition, index, caller.id
            )):
        is_creation = True
    if definition.is_constructor and not is_creation:
        return False
    if is_creation and definition.is_constructor:
        same_file = call.path == definition.path
        imports_match = _file_imports_target(
            call.path, _visible_imports(index, call.path, caller.id), definition, lang
        )
        alias_or_type = call.callee_name in _class_names_and_aliases(
            call.path, definition, index, caller.id
        )
        java_same_package = (lang == "java" and _java_same_package(call.path, definition.path, index))
        return (same_file or imports_match or java_same_package) and alias_or_type

    # Same-file top-level functions can be resolved directly by their declaration
    # name, provided the call is not an unrelated object's same-named method.
    if call.path == definition.path and not definition.class_name:
        expression = (call.callee_expression or "").strip()
        if expression == call.callee_name:
            return True
        # `module.function()` is allowed only when its module qualifier comes from
        # an import that resolves to the definition's file.
        if _file_imports_target(
                call.path, _visible_imports(index, call.path, caller.id), definition, lang):
            aliases = _imported_aliases_for_definition(
                call.path, definition, index, caller.id
            )
            receiver = expression.rsplit(".", 1)[0] if "." in expression else ""
            if receiver and (receiver in aliases or receiver.split(".")[-1] in aliases):
                return True
        return False

    # Intra-class calls are strong evidence. Python/JS instance methods must use
    # self/this (or an explicitly typed receiver); Java also permits bare method calls.
    if call.path == definition.path and caller.class_name == definition.class_name and definition.class_name:
        expression = (call.callee_expression or "").strip()
        if lang == "java" and expression == definition.name:
            return True
        receiver = expression.rsplit(".", 1)[0] if "." in expression else ""
        if receiver in {"self", "this", "cls"}:
            return True
        if _receiver_matches_definition(call, caller, definition,
                                        _receiver_scope_text(caller, index), index):
            return True

    # Cross-file references need a resolved import, or (for Java) same-package
    # access plus explicit evidence that the target class is referenced.
    imports = _visible_imports(index, call.path, caller.id)
    imports_match = _file_imports_target(call.path, imports, definition, lang)
    java_package_match = False
    source_text = _read_source_text(index, call.path)
    if lang == "java" and definition.class_name and _java_same_package(call.path, definition.path, index):
        clean = _java_code_without_comments_and_strings(source_text)
        java_package_match = bool(re.search(
            r"(?<![\w$])" + re.escape(class_leaf) + r"(?![\w$])", clean
        ))

    if not definition.class_name:
        if not (imports_match or (lang == "java" and java_package_match)):
            return False
        expression = (call.callee_expression or "").strip()
        aliases = _imported_aliases_for_definition(
            call.path, definition, index, caller.id
        )
        if expression == call.callee_name:
            # A bare call across files must bind the imported function under this
            # exact local name; importing an unrelated symbol from the same module
            # is not sufficient evidence.
            return call.callee_name in aliases
        receiver = expression.rsplit(".", 1)[0] if "." in expression else ""
        if receiver:
            module_aliases = _imported_module_aliases_for_definition(
                call.path, definition, index, caller.id
            )
            return (receiver in module_aliases or receiver.split(".")[-1] in module_aliases
                    or receiver in aliases or receiver.split(".")[-1] in aliases)
        return False

    if _is_java_static_import_of_method(call.path, definition, index) and call.callee_name == definition.name:
        return True
    if not (imports_match or java_package_match):
        return False
    return _receiver_matches_definition(
        call, caller, definition, _receiver_scope_text(caller, index), index
    )

def _candidate_calls_for_target(target: FunctionInfo, index: Dict[str, Any]) -> List[CallSite]:
    """Get only call sites whose callee name can refer to the target.

    The previous implementation visited every call site for every target, which
    made bulk extraction scale as O(targets * all_calls). This uses name indexes
    first and checks imports only in files whose import text could mention the
    target symbol/class/module, preserving explicit alias support without scanning
    unrelated call sites.
    """
    language = target.language
    calls_by_name = index.get("calls_by_name", {})
    calls_by_path_name = index.get("calls_by_path_name", {})
    candidate_names = {target.name}
    class_leaf = _function_class_leaf(target)
    if target.is_constructor and class_leaf:
        candidate_names.add(class_leaf)
    result: List[CallSite] = []
    seen: Set[Tuple[str, int, int, str]] = set()

    def add_calls(items: Iterable[CallSite]):
        for item in items:
            identity = (item.path, item.line, item.end_line, item.callee_expression)
            if identity not in seen:
                seen.add(identity)
                result.append(item)

    for name in candidate_names:
        add_calls(calls_by_name.get((language, name), []))

    # Find alias call sites only where an import statement plausibly refers to the
    # target symbol, its class, or its source module. This avoids resolving aliases
    # for every unrelated file/call in the repository.
    symbol_hints = {target.name, class_leaf, Path(_without_source_extension(target.path)).name}
    symbol_hints = {value for value in symbol_hints if value}
    if symbol_hints:
        hint_pattern = re.compile(
            r"(?<![\w$])(?:" + "|".join(re.escape(value) for value in sorted(symbol_hints, key=len, reverse=True))
            + r")(?![\w$])"
        )
        # Method aliases do not change the called member name (e.g. alias.foo()
        # still has callee name foo). Alias expansion is necessary for imported
        # top-level functions and constructor/class aliases only.
        needs_symbol_aliases = (not target.class_name) or target.is_constructor
        imports_by_file = index.get("all_imports_by_file", index.get("imports_by_file", {}))
        if needs_symbol_aliases:
            import_paths_by_identifier = index.get("import_paths_by_identifier", {})
            paths_with_calls = index.get("paths_with_calls_by_language", {}).get(language, set())
            possible_import_paths: Set[str] = set()
            for hint in symbol_hints:
                possible_import_paths.update(import_paths_by_identifier.get((language, hint), set()))
            for source_path in possible_import_paths.intersection(paths_with_calls):
                if source_path == target.path:
                    continue
                imports = imports_by_file.get(source_path, [])
                if not imports or not any(hint_pattern.search(statement) for statement in imports):
                    continue
                aliases = _imported_aliases_for_definition(
                    source_path, target, index, include_all_scopes=True
                )
                if target.is_constructor:
                    aliases.update(_class_names_and_aliases(
                        source_path, target, index, include_all_scopes=True
                    ))
                for alias in aliases:
                    if alias and alias not in candidate_names:
                        add_calls(calls_by_path_name.get((source_path, language, alias), []))

    return result


def build_context_for_target(target: FunctionInfo, index: Dict[str, Any],
                             max_code_chars: int = 12000,
                             max_definitions_per_symbol: int = 5,
                             max_related_types: int = 30,
                             max_callers: int = 50,
                             max_tests: int = 50) -> Dict[str, Any]:
    """Build a context bundle containing only source snippets and their file paths."""
    calls: List[CallSite] = index["calls"]
    functions_by_id: Dict[str, FunctionInfo] = index["functions_by_id"]
    by_name = index["by_name"]
    caller_calls: Dict[str, List[CallSite]] = index["caller_calls"]

    # Resolve direct callers against actual declaration candidates. A matching
    # method name is only a prefilter; file/module imports, class/receiver evidence,
    # and overload arity must support the candidate definition.
    call_groups: Dict[str, List[CallSite]] = defaultdict(list)
    definitions_by_name = index["by_name"]
    candidate_calls = _candidate_calls_for_target(target, index)
    target_label = f"{target.path}::{target.qualified_name or target.name}"
    print(
        f"[调用者解析] {target_label}：候选调用点 {len(candidate_calls)} 个；开始精确匹配",
        flush=True,
    )
    caller_scan_started = time.monotonic()
    for call_number, call in enumerate(candidate_calls, 1):
        if len(candidate_calls) >= 10000 and call_number % 10000 == 0:
            print(
                f"[调用者解析] {target_label}：已检查 {call_number}/{len(candidate_calls)} 个调用点，"
                f"已匹配调用者 {len(call_groups)} 个，耗时 {time.monotonic() - caller_scan_started:.1f}s",
                flush=True,
            )
        if call.language != target.language or not call.caller_id or call.caller_id == target.id:
            continue
        caller = functions_by_id.get(call.caller_id)
        if caller is None:
            continue

        # Fast reject against the exact target first. On large repositories, a common
        # callee name may have hundreds of definitions; don't resolve all of them for
        # every call site unless this call can actually refer to the requested target.
        if not _call_resolves_to_definition(call, caller, target, index):
            continue

        same_named_definitions = list(definitions_by_name.get((target.language, call.callee_name), []))
        if target.name != call.callee_name:
            same_named_definitions.extend(definitions_by_name.get((target.language, target.name), []))
        if target.is_constructor:
            same_named_definitions = [f for f in same_named_definitions
                                      if f.is_constructor and (f.name == target.name or _function_class_leaf(f) == call.callee_name)]
        resolved = [definition for definition in same_named_definitions
                    if definition.id == target.id or _call_resolves_to_definition(call, caller, definition, index)]
        local_resolved = [definition for definition in resolved if definition.path == call.path]
        if local_resolved:
            resolved = local_resolved
        resolved = _narrow_by_arity(call, resolved)
        if any(definition.id == target.id for definition in resolved):
            call_groups[caller.id].append(call)

    print(
        f"[调用者解析] {target_label}：精确匹配完成，涉及 {len(call_groups)} 个函数，"
        f"耗时 {time.monotonic() - caller_scan_started:.1f}s",
        flush=True,
    )
    direct_callers: List[Dict[str, str]] = []
    related_test_candidates: List[Tuple[FunctionInfo, Dict[str, str]]] = []
    for caller_id, matched_calls in call_groups.items():
        caller = functions_by_id.get(caller_id)
        if caller is None:
            continue
        record = _source_record(caller.path, _function_source(caller))
        if caller.is_test:
            related_test_candidates.append((caller, record))
        else:
            direct_callers.append(record)

    # Test functions need explicit source-module association after the call itself
    # has been statically resolved; never fall back to same-name-only matching.
    selected_test_candidates = []
    for pair in related_test_candidates:
        test_info = pair[0]
        test_imports = _visible_imports(index, test_info.path, test_info.id)
        if test_info.path == target.path:
            # The call was already resolved to the exact target above; a same-file
            # test naturally needs no import declaration.
            matched = True
        elif target.language == "java":
            test_source = _read_source_text(index, test_info.path)
            target_source = _read_source_text(index, target.path)
            matched = _java_test_references_target(
                test_info.path, test_imports, target, target_source, test_source
            )
        else:
            matched = _file_imports_target(
                test_info.path, test_imports, target, target.language
            )
        if matched:
            selected_test_candidates.append(pair)
    related_tests = [record for _, record in selected_test_candidates]
    print(
        f"[测试筛选] {target_label}：保留 {len(related_tests)} 个相关测试，"
        f"直接调用者候选 {len(direct_callers)} 个",
        flush=True,
    )

    # Deterministic order and conservative caps.
    direct_callers = sorted({(x["file"], x["code"]): x for x in direct_callers}.values(),
                            key=lambda x: (x["file"], x["code"]))[:max_callers]
    related_tests = sorted({(x["file"], x["code"]): x for x in related_tests}.values(),
                           key=lambda x: (x["file"], x["code"]))[:max_tests]

    # Resolve only definitions that the call can reach in its lexical/module/class
    # context. Ambiguous same-name definitions are discarded instead of emitting all
    # matches across the repository.
    target_calls = caller_calls.get(target.id, [])
    dependency_definitions: Dict[str, FunctionInfo] = {}
    imported_definitions_by_alias: Optional[Dict[str, List[FunctionInfo]]] = None
    visible_target_imports = _visible_imports(index, target.path, target.id)
    target_import_aliases = _import_alias_originals(
        visible_target_imports, target.language
    )
    renamed_import_aliases = {
        alias
        for statement in visible_target_imports
        for original, alias in _import_alias_pairs(statement, target.language)
        if original == "default" or original != alias
    }
    for call in target_calls:
        if not call.callee_name or call.callee_name == target.name:
            continue
        candidate_names = {call.callee_name}
        candidate_names.update(target_import_aliases.get(call.callee_name, set()))
        candidates: List[FunctionInfo] = []
        for symbol in candidate_names:
            candidates.extend(by_name.get((target.language, symbol), []))
        if not candidates and call.callee_name in renamed_import_aliases:
            # Build the expensive import-alias reverse index once per target,
            # rather than rescanning every repository definition for every call.
            if imported_definitions_by_alias is None:
                alias_index: Dict[str, List[FunctionInfo]] = defaultdict(list)
                for definition in index["functions"]:
                    if definition.language != target.language:
                        continue
                    for alias in _imported_aliases_for_definition(
                            target.path, definition, index, target.id):
                        alias_index[alias].append(definition)
                imported_definitions_by_alias = alias_index
            candidates = list(imported_definitions_by_alias.get(call.callee_name, []))
        # Aliased imported constructors may be bound to a class name rather than the
        # declaration's textual constructor name; search the matching constructor set.
        if not candidates and call.syntax_kind in {
            "call", "object_creation_expression", "new_expression"
        }:
            candidates = [f for f in index["functions"]
                          if f.language == target.language and f.is_constructor
                          and call.callee_name in _class_names_and_aliases(
                              target.path, f, index, target.id
                          )]
        candidates = [candidate for candidate in candidates
                      if candidate.id != target.id
                      and _call_resolves_to_definition(call, target, candidate, index)]
        local_candidates = [candidate for candidate in candidates if candidate.path == target.path]
        if local_candidates:
            candidates = local_candidates
        candidates = _narrow_by_arity(call, candidates)
        # If resolution is still ambiguous, don't guess which body implements the call.
        if len(candidates) == 1:
            dependency_definitions[candidates[0].id] = candidates[0]

    dependencies: List[Dict[str, str]] = []
    print(
        f"[依赖解析] {target_label}：解析到 {len(dependency_definitions)} 个直接依赖定义",
        flush=True,
    )
    for definition in sorted(dependency_definitions.values(),
                             key=lambda item: (item.path, item.start_line, item.name)):
        dependencies.append(_source_record(definition.path, _function_source(definition)))

    # Target class context is limited to constructors and fields, each stored as source + file.
    class_context = find_class_context(target, index["classes"])
    class_members: List[Dict[str, str]] = []
    if class_context:
        for code in class_context.get("constructors", []):
            if code.strip():
                class_members.append(_source_record(target.path, code))
        for code in class_context.get("fields", []):
            if code.strip():
                class_members.append(_source_record(target.path, code))

    evidence_text = "\n".join([
        _function_source(target),
        *(x["code"] for x in related_tests),
        *(x["code"] for x in direct_callers),
        *(x["code"] for x in dependencies),
        *(x["code"] for x in class_members),
    ])
    type_definitions = relevant_type_definitions(
        index, target, evidence_text, max_related_types
    )

    # Imports are intentionally limited to the target function's own file.
    target_imports = _visible_imports(index, target.path, target.id)
    # Import relevance is determined only from the target itself. Tests, callers,
    # dependencies and class members must not cause unrelated file imports to leak
    # into the target's final import list.
    target_context_text = _function_source(target)
    target_imports = filter_imports(target_imports, target.language, target_context_text)
    # Keep imports as plain source strings under target_function (no per-import metadata).
    target_function = _source_record(target.path, _function_source(target))
    target_function["imports"] = target_imports

    # Context fragments remain source-only records; no analysis/version/summary metadata.
    return {
        "target_function": target_function,
        "related_tests": related_tests,
        "direct_callers": direct_callers,
        "dependencies": dependencies,
        "class_context": class_members,
        "related_types": type_definitions,
    }


def build_repository_index(repo: str | Path, max_file_bytes: int = 2_000_000,
                           allowed_files: Optional[Iterable[str]] = None,
                           max_code_chars: int = 12000) -> Dict[str, Any]:
    root = Path(repo).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Repository directory does not exist: {root}")
    return scan_repository(root, max_file_bytes, allowed_files, max_code_chars)


def build_function_context(repo: str | Path, target_file: str, target_name: str,
                           target_class: Optional[str] = None,
                           target_line: Optional[int] = None,
                           max_code_chars: int = 12000,
                           max_file_bytes: int = 2_000_000,
                           max_definitions_per_symbol: int = 5,
                           max_related_types: int = 30,
                           repository_index: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    index = repository_index or build_repository_index(repo, max_file_bytes, max_code_chars=max_code_chars)
    record = {"src_file": target_file, "name": target_name, "class_name": target_class, "start_line": target_line}
    target = match_target(record, index)
    return build_context_for_target(target, index, max_code_chars,
                                    max_definitions_per_symbol, max_related_types)


def enrich_function_record(record: Dict[str, Any], repo: str | Path,
                           repository_index: Optional[Dict[str, Any]] = None,
                           **kwargs: Any) -> Dict[str, Any]:
    """Compatibility helper: add the restricted static context to a selected function record."""
    enriched = dict(record)
    try:
        max_file_bytes = kwargs.pop("max_file_bytes", 2_000_000)
        max_code_chars = kwargs.pop("max_code_chars", 12000)
        index = repository_index or build_repository_index(
            repo,
            max_file_bytes,
            max_code_chars=max_code_chars,
        )
        target = match_target(record, index)
        context = build_context_for_target(
            target,
            index,
            max_code_chars=max_code_chars,
            max_definitions_per_symbol=kwargs.pop("max_definitions_per_symbol", 5),
            max_related_types=kwargs.pop("max_related_types", 30),
            max_callers=kwargs.pop("max_callers", 50),
            max_tests=kwargs.pop("max_tests", 50),
        )
        enriched["context"] = context
        enriched["context_status"] = "ok"
    except Exception as exc:
        enriched["context"] = {"analysis": {"status": "unavailable", "error": str(exc)}}
        enriched["context_status"] = "error"
    return enriched


def annotate_outgoing_degree(record: Dict[str, Any], repository_index: Dict[str, Any]) -> Dict[str, Any]:
    """Compatibility helper for old filtering scripts."""
    result = dict(record)
    try:
        target = match_target(record, repository_index)
        result["outgoing_degree"] = repository_index["outgoing_degree"].get(target.id, 0)
        result["unique_callee_count"] = result["outgoing_degree"]
    except Exception:
        result["outgoing_degree"] = None
        result["unique_callee_count"] = None
    return result


def function_records_from_document(data: Any) -> List[Dict[str, Any]]:
    """Return the mutable record list inside an input JSON document."""
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        records = None
        for key in ("selected_functions", "functions", "results", "all_selected_methods"):
            if isinstance(data.get(key), list):
                records = data[key]
                break
        if records is None:
            raise ValueError(
                "Input JSON object must contain a list under selected_functions, functions, results, or all_selected_methods."
            )
    else:
        raise ValueError("Input JSON must be a list of function records or an object containing a function list.")

    if not all(isinstance(record, dict) for record in records):
        raise ValueError("Each function record in the input JSON must be an object.")
    return records


def load_function_records(path: Path) -> List[Dict[str, Any]]:
    """Compatibility helper: load only the function record list."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return function_records_from_document(data)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract only priority-1/priority-2 static context for specification generation."
    )
    parser.add_argument("--repo", required=True, help="Repository root")
    parser.add_argument("--selected-functions", help="JSON list produced by the function filter; enrich every record")
    parser.add_argument("--target-file", help="Single target file, relative to --repo")
    parser.add_argument("--target-name", help="Single target function/method name")
    parser.add_argument("--target-class", help="Optional target class name")
    parser.add_argument("--target-line", type=int, help="Optional line number inside target declaration")
    parser.add_argument("--output", default="spec_context.json", help="Output JSON path")
    parser.add_argument("--max-code-chars", type=int, default=12000, help="Maximum chars per code fragment")
    parser.add_argument("--max-file-bytes", type=int, default=2_000_000, help="Skip files bigger than this size")
    parser.add_argument("--max-definitions-per-symbol", type=int, default=5, help="Max same-name dependency definitions")
    parser.add_argument("--max-related-types", type=int, default=30, help="Max referenced type definitions")
    parser.add_argument("--max-callers", type=int, default=50, help="Max direct callers per target")
    parser.add_argument("--max-tests", type=int, default=50, help="Max directly related test methods per target")
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    if args.selected_functions:
        if args.target_file or args.target_name:
            parser.error("Use either --selected-functions or --target-file/--target-name, not both.")
    elif not (args.target_file and args.target_name):
        parser.error("Specify --selected-functions or both --target-file and --target-name.")

    repo = Path(args.repo).expanduser().resolve()
    try:
        print(f"[启动] 开始对仓库进行静态索引：{repo}", flush=True)
        index = build_repository_index(repo, args.max_file_bytes, max_code_chars=args.max_code_chars)
        print(f"仓库: {repo}")
        print(f"静态索引完成：函数/方法 {len(index['functions'])} 个，调用点 {len(index['calls'])} 个，类型定义 {len(index['classes'])} 个")
        if index["skipped"]:
            print(f"因文件过大或读取失败跳过 {len(index['skipped'])} 个文件")

        if args.selected_functions:
            input_path = Path(args.selected_functions).expanduser().resolve()
            input_document = json.loads(input_path.read_text(encoding="utf-8"))
            records = function_records_from_document(input_document)
            succeeded = 0
            failed = 0
            context_started = time.monotonic()
            for number, record in enumerate(records, 1):
                # Append context to each original record rather than emitting a separate context-only JSON.
                # Keep the input schema/metadata intact and initialize context fields for failed targets too.
                record["related_tests"] = []
                record["direct_callers"] = []
                record["dependencies"] = []
                print(
                    f"[上下文提取] 正在处理 {number}/{len(records)}："
                    f"{record.get('src_file') or record.get('file')}::{record.get('name')}；"
                    f"已完成 {succeeded}，失败 {failed}，"
                    f"总耗时 {time.monotonic() - context_started:.1f}s",
                    flush=True,
                )
                item_started = time.monotonic()
                try:
                    target = match_target(record, index)
                    context = build_context_for_target(
                        target, index,
                        max_code_chars=args.max_code_chars,
                        max_definitions_per_symbol=args.max_definitions_per_symbol,
                        max_related_types=args.max_related_types,
                        max_callers=args.max_callers,
                        max_tests=args.max_tests,
                    )
                    # The original record already has target code and class metadata.
                    # Reuse the context's filtered imports as a plain string list.
                    record["imports"] = context.get("target_function", {}).get("imports", [])
                    record["related_tests"] = context.get("related_tests", [])
                    record["direct_callers"] = context.get("direct_callers", [])
                    record["dependencies"] = context.get("dependencies", [])
                    record["related_types"] = context.get("related_types", [])
                    succeeded += 1
                    print(
                        f"[上下文提取] 完成 {number}/{len(records)}，"
                        f"测试 {len(record['related_tests'])}，"
                        f"直接调用者 {len(record['direct_callers'])}，"
                        f"依赖 {len(record['dependencies'])}，"
                        f"本目标耗时 {time.monotonic() - item_started:.1f}s，"
                        f"累计成功 {succeeded}",
                        flush=True,
                    )
                except Exception as exc:
                    failed += 1
                    print(
                        f"[{number}/{len(records)}] 上下文提取失败："
                        f"{record.get('src_file') or record.get('file')}::{record.get('name')}：{exc}",
                        flush=True,
                    )
            # Preserve the original top-level list/object (including any wrapper fields).
            output_data = input_document
            print(f"上下文已拼接回原始 JSON：成功 {succeeded}，失败 {failed}，输入目标数 {len(records)}")
        else:
            record = {
                "src_file": args.target_file,
                "name": args.target_name,
                "class_name": args.target_class,
                "start_line": args.target_line,
            }
            target = match_target(record, index)
            output_data = build_context_for_target(
                target, index,
                max_code_chars=args.max_code_chars,
                max_definitions_per_symbol=args.max_definitions_per_symbol,
                max_related_types=args.max_related_types,
                max_callers=args.max_callers,
                max_tests=args.max_tests,
            )

        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(output_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"结果已保存: {output}")
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
