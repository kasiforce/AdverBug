"""Shared predicates for externally callable production functions."""

from __future__ import annotations

import ast
import re
import textwrap


def has_nonempty_callable_body(code: str, language: str) -> bool:
    """Return whether a callable contains a real body statement/expression."""
    if language == "python":
        try:
            tree = ast.parse(textwrap.dedent(code))
        except (IndentationError, SyntaxError):
            return False
        function = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ),
            None,
        )
        if function is None:
            return False
        for statement in function.body:
            if isinstance(statement, ast.Pass):
                continue
            if isinstance(statement, ast.Expr) and (
                isinstance(statement.value, ast.Constant)
                and (isinstance(statement.value.value, str) or statement.value.value is Ellipsis)
            ):
                continue
            return True
        return False

    without_comments = re.sub(r"/\*[\s\S]*?\*/|//[^\n]*", "", code)
    if language == "javascript" and "=>" in without_comments:
        arrow_body = without_comments.split("=>", 1)[1].strip()
        if not arrow_body.startswith("{"):
            return bool(arrow_body.rstrip("; "))
    left = without_comments.find("{")
    right = without_comments.rfind("}")
    return left >= 0 and right > left and bool(
        without_comments[left + 1 : right].strip("; \t\r\n")
    )
