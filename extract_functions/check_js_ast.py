
from collections import Counter
from multi_parser import js_parser

SOURCE = b"""
export function declaredFn(x) {
    return x;
}

export const expressionFn = function (x) {
    return x;
};

export const arrowFn = (x) => x;

export const ClassExpr = class {
    method() {
        return 1;
    }
};

export class ClassDecl {
    method() {
        return 1;
    }
}

export var varFn = function (x) {
    return x;
};

export function* generatorFn() {
    yield 1;
}

export default function (x) {
    return x;
}

export default (x) => x;
"""

tree = js_parser.parse(SOURCE)
root = tree.root_node

# 递归遍历所有 AST 节点
def walk(node):
    yield node
    for child in node.children:
        yield from walk(child)


nodes = list(walk(root))
counts = Counter(node.type for node in nodes)

# 重点关注的节点类型
watch_types = {
    "export_statement",
    "function_declaration",
    "function_expression",
    "function",
    "generator_function_declaration",
    "generator_function",
    "arrow_function",
    "class_declaration",
    "class_expression",
    "class",
    "lexical_declaration",
    "variable_declaration",
    "variable_declarator",
    "method_definition",
}

print("========== AST 节点类型统计 ==========")
for node_type in sorted(watch_types):
    print(f"{node_type:32s}: {counts[node_type]}")

print("\n========== 具体节点及其父节点 ==========")
for node in nodes:
    if node.type not in watch_types:
        continue

    parent_type = node.parent.type if node.parent else "<root>"
    text = SOURCE[node.start_byte:node.end_byte].decode(
        "utf-8", errors="replace"
    ).replace("\n", "\\n")

    print(
        f"type={node.type:30s} "
        f"parent={parent_type:25s} "
        f"line={node.start_point[0] + 1:3d} "
        f"text={text[:120]}"
    )

print("\n========== 解析错误检查 ==========")
print("root_node.has_error =", root.has_error)
