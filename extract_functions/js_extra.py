from inspect import stack
import os
import json
import re
import argparse
from pathlib import Path
from typing import List, Dict, Any, Tuple, Set
from collections import defaultdict
from unittest import result
from multi_parser import js_parser

try:
    import lizard
except ImportError:  # pragma: no cover - fallback is used only without lizard
    lizard = None


IGNORED_DIRS = {
    'test', 'tests', '__tests__', '__pycache__', '.git', '.svn', '.hg',
    'node_modules', 'vendor', 'bower_components', 'dist', 'build', 'coverage',
    '.nyc_output', '.cache', '.parcel-cache', '.vscode', '.idea',
    'docs', 'doc', 'example', 'examples', 'demo', 'demos', 'benchmark',
    'benchmarks', 'script', 'scripts',
}

TEST_FILE_PATTERNS = [
    re.compile(r'^test_.*\.(?:js|jsx|mjs|cjs)$', re.IGNORECASE),
    re.compile(r'.*[_\.]test\.(?:js|jsx|mjs|cjs)$', re.IGNORECASE),
    re.compile(r'.*[_\.]spec\.(?:js|jsx|mjs|cjs)$', re.IGNORECASE),
]

CLASS_NODE_TYPES = {
    'class_declaration',
    'class_expression',
    'class',
}

ANONYMOUS_DEFAULT_CLASS = "__anonymous_default_export_class__"
# Internal sentinel: unlike the string "default", this means the CJS root export.
COMMONJS_DEFAULT_EXPORT = "__commonjs_root_default_export__"

FUNCTION_DECLARATION_TYPES = {
    'function_declaration',
    'generator_function_declaration',
}

FUNCTION_VALUE_TYPES = {
    'function',
    'function_expression',
    'arrow_function',
    'generator_function',
}

def discover_javascript_files(project_root: str) -> List[str]:
    """递归收集生产 JavaScript 文件，排除测试及常见非生产目录。"""
    root_path = Path(project_root).resolve()
    source_files: List[str] = []
    extensions = {'.js', '.jsx', '.mjs', '.cjs'}
    for current_root, dirs, files in os.walk(root_path):
        dirs[:] = [
            d for d in dirs
            if d.lower() not in IGNORED_DIRS
            and not d.lower().endswith('.egg-info')
            and not d.startswith('.')
        ]
        for filename in files:
            if Path(filename).suffix.lower() not in extensions:
                continue
            if any(pattern.match(filename) for pattern in TEST_FILE_PATTERNS):
                continue
            full_path = Path(current_root) / filename
            relative_parts = {part.lower() for part in full_path.relative_to(root_path).parts[:-1]}
            if relative_parts.intersection(IGNORED_DIRS):
                continue
            source_files.append(str(full_path))
    return sorted(set(source_files))


class JSProjectTestScopeExtractor:
    """提取生产 JavaScript 中的非私有函数，并按阈值筛选。

    默认只提取可从模块外部访问的导出函数和导出类的公有方法。
    ``only_exported=False`` 仅适合代码分析，不应直接作为外部单元测试候选。
    """

    def __init__(self, project_root, file_list, output_file=None,
                 min_loc_threshold=50, min_complexity_threshold=10,
                 min_outgoing_degree_threshold=5, random_seed=42,
                 only_exported=True, min_project_functions=1):
        self.project_root = str(Path(project_root).resolve())
        self.files = file_list
        self.output_file = output_file
        self.min_loc_threshold = min_loc_threshold
        self.min_complexity_threshold = min_complexity_threshold
        self.min_outgoing_degree_threshold = min_outgoing_degree_threshold
        self.random_seed = random_seed
        self.only_exported = only_exported
        self.min_project_functions = min_project_functions

        self.stats = defaultdict(lambda: defaultdict(int))
        self.metric_stats = defaultdict(int)

    # ------------------------------------------------------------------
    # 复杂度 / LOC
    # ------------------------------------------------------------------
    def _analyze_file_with_lizard(self, file_path, code):
        """用 Lizard 一次分析完整源文件。

        类方法 / 对象方法的源码片段脱离 class/object 上下文后
        不是独立合法的 JavaScript，不能逐方法直接交给 Lizard。
        """
        if lizard is None:
            return []
        try:
            source = code.decode('utf-8', errors='replace') \
                if isinstance(code, bytes) else code
            report = lizard.analyze_file.analyze_source_code(file_path, source)
            return list(report.function_list or [])
        except Exception as exc:
            print(
                f"[warn] Lizard 无法分析完整文件 {file_path}: "
                f"{type(exc).__name__}: {exc}"
            )
            return []

    @staticmethod
    def _lizard_name_matches(candidate_name, function_name):
        if not function_name:
            return candidate_name in ('(anonymous)', 'anonymous', 'default')
        if candidate_name == function_name:
            return True
        return bool(re.search(
            rf'(?:^|[.:]){re.escape(function_name)}$',
            candidate_name or '',
        ))

    def _match_lizard_function(self, function_node, lizard_functions,
                               function_name=None):
        """用源码位置将 Tree-sitter 函数节点与 Lizard 结果对应。"""
        if function_node is None or not lizard_functions:
            return None

        start_line = function_node.start_point[0] + 1
        end_line = function_node.end_point[0] + 1
        tree_span = max(1, end_line - start_line + 1)
        candidates = []
        for item in lizard_functions:
            item_start = int(getattr(item, 'start_line', 0) or 0)
            item_end = int(getattr(item, 'end_line', item_start) or item_start)
            if item_start > end_line or item_end < start_line:
                continue
            name_matches = self._lizard_name_matches(
                getattr(item, 'name', ''), function_name
            )

            # Lizard 偶尔会在大型 class 中漏掉方法边界，把后续若干方法
            # 全部并入前一个方法。此时仅凭“源码范围有交集”会把同一组被
            # 放大的指标赋给多个 Tree-sitter 节点。具名函数必须名称一致，
            # 且两端边界应与 Tree-sitter 的范围大致相符；否则交给下方的
            # 单函数包装分析处理。
            if function_name and not name_matches:
                continue
            boundary_tolerance = max(3, int(tree_span * 0.20))
            if (abs(item_start - start_line) > boundary_tolerance or
                    abs(item_end - end_line) > boundary_tolerance):
                continue

            score = (
                0 if name_matches else 1,
                abs(item_start - start_line) + abs(item_end - end_line),
                abs(item_start - start_line),
            )
            candidates.append((score, item))

        if not candidates:
            return None
        candidates.sort(key=lambda pair: pair[0])
        return candidates[0][1]

    @staticmethod
    def _approximate_param_count(code):
        param_match = re.search(r'\((.*?)\)', code, re.DOTALL)
        param_text = param_match.group(1).strip() if param_match else ''
        return len([
            p for p in param_text.split(',') if p.strip()
        ]) if param_text else 0

    def _compute_complexity_and_loc(self, code, function_node=None,
                                    lizard_functions=None,
                                    function_name=None):
        """获取单个函数指标，优先使用完整文件的 Lizard 结果。"""
        loc = len([line for line in code.splitlines() if line.strip()])
        function = self._match_lizard_function(
            function_node, lizard_functions, function_name
        )
        if function is not None:
            self.metric_stats['lizard_file_match'] += 1
            return (
                int(getattr(function, 'cyclomatic_complexity', 1)),
                int(getattr(function, 'nloc', loc)),
                len(getattr(function, 'full_parameters', []) or []),
            )

        # 完整文件未匹配时，先将片段包装成合法的 class/object
        # 上下文，仍由 Lizard 计算，不再静默默认为 1。
        if lizard is not None:
            safe_method_code = code
            if function_name:
                # Lizard 会把名为 set/get 的普通方法误当成属性访问器。
                # 只改写方法头的名称，参数和函数体保持不变。
                safe_method_code = re.sub(
                    rf'^(\s*(?:async\s+)?(?:\*\s*)?)'
                    rf'{re.escape(function_name)}(\s*\()',
                    r'\1__lizardMeasuredFunction\2',
                    code,
                    count=1,
                )
            wrapped_sources = (
                code,
                f'class __LizardMetricWrapper__ {{\n{code}\n}}',
                f'const __lizardMetricWrapper__ = {{\n{code}\n}};',
                f'class __LizardMetricWrapper__ {{\n{safe_method_code}\n}}',
            )
            for wrapped in wrapped_sources:
                try:
                    report = lizard.analyze_file.analyze_source_code(
                        'metric_fragment.js', wrapped
                    )
                    matches = list(report.function_list or [])
                    if not matches:
                        continue
                    named = [
                        item for item in matches
                        if self._lizard_name_matches(
                            getattr(item, 'name', ''), function_name
                        )
                    ]
                    function = (named or matches)[0]
                    self.metric_stats['lizard_wrapped_fragment'] += 1
                    return (
                        int(getattr(function, 'cyclomatic_complexity', 1)),
                        int(getattr(function, 'nloc', loc)),
                        len(getattr(function, 'full_parameters', []) or []),
                    )
                except Exception:
                    continue

        # 不用正则近似圈复杂度：它会把嵌套函数的分支也计入，
        # 与 Lizard 口径不可比。记为 0 后由现有 CC>=10 规则排除。
        self.metric_stats['lizard_unmeasured'] += 1
        return 0, loc, self._approximate_param_count(code)

    def _compute_outgoing_degree(self, function_node) -> int:
        """统计函数内部不重复的调用表达式数量，不解析嵌套函数。"""
        callees: Set[str] = set()
        nested_scopes = {
            'function_declaration',
            'generator_function_declaration',
            'function',
            'function_expression',
            'generator_function',
            'arrow_function',
            'class_declaration',
            'class_expression',
            'class',
        }

        def visit(node, is_root=False):
            if not is_root and node.type in nested_scopes:
                return
            if node.type == 'call_expression':
                function = node.child_by_field_name('function')
                if function is not None:
                    callees.add(function.text.decode('utf-8', errors='replace').strip())
            for child in node.children:
                visit(child)

        visit(function_node, is_root=True)
        return len(callees)

    # ------------------------------------------------------------------
    # 项目级遍历
    # ------------------------------------------------------------------
    def _extract_project_functions(self):
        all_functions = []
        for file_path in self.files:
            try:
                file_funcs = self._extract_functions_from_file(file_path)
                all_functions.extend(file_funcs)
            except Exception as exc:
                print(f"Error processing {file_path}: {exc}")
        return all_functions

    # ------------------------------------------------------------------
    # 单文件提取
    # ------------------------------------------------------------------
    def _extract_functions_from_file(self, file_path):
        with open(file_path, 'rb') as f:
            code = f.read()

        tree = js_parser.parse(code)
        root_node = tree.root_node
        lizard_functions = self._analyze_file_with_lizard(file_path, code)

        # 一次性算好：imports / 类信息 / 当前文件的导出名单
        imports = self._extract_imports(root_node, code)
        class_contexts = self._extract_all_class_info(root_node, code, file_path)
        exported_names = self._collect_exported_names(root_node, code)

        # 被导出的类（名字命中即可；行内/底部 export 都已在 exported_names 里）
        exported_classes = {n for n in exported_names if n in class_contexts}
        # 每个类的导出元数据：
        # class_name -> (class_export_kind, class_exported_name)
        class_export_metadata = {}

        for candidate in self._walk_nodes(root_node):
            if candidate.type not in CLASS_NODE_TYPES:
                continue

            # 解析器也可能把 class 关键字本身表示为 class 节点。
            # 这里只处理真正包含 class_body 的类节点。
            if candidate.type == 'class' and not any(
                child.type == 'class_body'
                for child in candidate.children
            ):
                continue

            class_name = self._get_class_name(candidate, code)

            if not class_name and self._is_default_export_node(candidate):
                class_name = ANONYMOUS_DEFAULT_CLASS

            cjs_class_export_name = self._get_cjs_assignment_export_name(
                candidate, code
            )
            if not class_name and cjs_class_export_name:
                class_name = ANONYMOUS_DEFAULT_CLASS

            if not class_name:
                continue

            class_export_kind, class_exported_name = (
                self._get_export_metadata(
                    root_node,
                    candidate,
                    class_name,
                    code,
                )
            )

            if class_export_kind is not None:
                class_export_metadata[class_name] = (
                    class_export_kind,
                    class_exported_name,
                )
            elif cjs_class_export_name:
                if cjs_class_export_name == COMMONJS_DEFAULT_EXPORT:
                    class_export_metadata[class_name] = (
                        'commonjs_default', None
                    )
                else:
                    class_export_metadata[class_name] = (
                        'commonjs_named', cjs_class_export_name
                    )
        # 包含通过导出元数据确认的类，包括匿名默认导出类
        exported_classes.update(class_export_metadata.keys())

        functions = self._extract_exported_object_functions(
            root_node,
            code,
            file_path,
            class_contexts,
            imports,
            lizard_functions,
        )

        stack = [(root_node, [], False)]

        while stack:
            node, current_classes, in_function_body = stack.pop()

            # ---------- 1. 类声明 / 类表达式 ----------
            if node.type in CLASS_NODE_TYPES:
                class_name = self._get_class_name(node, code)

                if not class_name and self._is_default_export_node(node):
                    class_name = ANONYMOUS_DEFAULT_CLASS
                if not class_name and self._get_cjs_assignment_export_name(node, code):
                    class_name = ANONYMOUS_DEFAULT_CLASS

                # Class declarations inside a function are lexical locals, so
                # their methods cannot be reached through the module's external
                # API.  JavaScript also uses underscore names for internal
                # classes; private ``#`` members are already covered by
                # _is_private_name when their method is visited.
                if in_function_body or (
                    class_name and self._is_private_name(class_name)
                ):
                    continue

                new_class_stack = (
                    current_classes + [class_name] if class_name else current_classes
                )
                for child in node.children:
                    if child.type == 'class_body':
                        for grandchild in reversed(child.children):
                            stack.append((grandchild, new_class_stack, in_function_body))
                        break
                continue
            # ---------- 匿名 default 导出 / CommonJS 直接导出函数 ----------
            if node.type in FUNCTION_VALUE_TYPES and not in_function_body:
                is_default_export = self._is_default_export_node(node)

                cjs_export_name = None
                if not current_classes:
                    cjs_export_name = self._get_cjs_assignment_export_name(
                        node, code
                    )

                if is_default_export or cjs_export_name:
                    # 属性导出使用公开属性名；
                    # 默认导出优先保留函数自己的名称，没有名称时使用 default
                    if is_default_export:
                        export_kind = 'esm_default'
                        exported_name = None

                        # 箭头函数参数可能被误识别为名字，必须显式处理。
                        if node.type == 'arrow_function':
                            func_name = None
                        else:
                            func_name = self._get_name(node, code)

                    elif cjs_export_name == COMMONJS_DEFAULT_EXPORT:
                        export_kind = 'commonjs_default'
                        exported_name = None

                        if node.type == 'arrow_function':
                            func_name = None
                        else:
                            func_name = self._get_name(node, code)

                    else:
                        export_kind = 'commonjs_named'
                        exported_name = cjs_export_name

                        if node.type == 'arrow_function':
                            func_name = None
                        else:
                            func_name = self._get_name(node, code)
                    # if cjs_export_name and cjs_export_name != 'default':
                    #     func_name = cjs_export_name
                    # else:
                    #     func_name = self._get_name(node, code) or 'default'

                    func_code = code[
                        node.start_byte:node.end_byte
                    ].decode('utf-8')

                    complexity, loc, param_count = (
                        self._compute_complexity_and_loc(
                            func_code, node, lizard_functions, func_name
                        )
                    )

                    if node.type == 'arrow_function':
                        is_async = self._is_async_arrow_function(node, code)
                    else:
                        is_async = self._is_async_function(node)

                    func_info = self._create_function_info(
                        node,
                        code,
                        file_path,
                        func_name,
                        'function',
                        current_classes,
                        class_contexts,
                        imports,
                        is_async=is_async,
                        is_exported=True,
                        code_override=func_code,
                        line_node_override=node,
                        export_kind=export_kind,
                        exported_name=exported_name,
                        complexity=complexity,
                        loc=loc,
                        param_count=param_count,
                    )

                    if func_info:
                        functions.append(func_info)

                    # 不把函数体内部的局部函数重复当成模块导出函数
                    self._push_function_body_children(
                        node, stack, current_classes, True
                    )
                    continue
            # ---------- 2. function_declaration ----------
            if node.type in FUNCTION_DECLARATION_TYPES:
                if in_function_body:
                    self._push_function_body_children(node, stack, current_classes, True)
                    continue

                func_name = self._get_name(node, code)
                member_export_kind, member_exported_name, member_name = (
                    self._get_exported_object_member_metadata(
                        root_node, func_name, code
                    )
                )
                alias_export_kind, alias_exported_name = (
                    self._get_local_alias_export_metadata(
                        root_node, func_name, code
                    )
                )
                is_exported = (
                    func_name in exported_names
                    or member_name is not None
                    or alias_exported_name is not None
                )
                if (func_name
                        and not self._is_private_name(func_name)
                        and (not self.only_exported or is_exported)):
                    func_code = code[node.start_byte:node.end_byte].decode('utf-8')
                    complexity, loc, param_count = self._compute_complexity_and_loc(
                        func_code, node, lizard_functions, func_name
                    )

                    export_kind, exported_name = self._get_export_metadata(
                        root_node, node, func_name, code
                    )
                    if member_name is not None:
                        export_kind = member_export_kind
                        exported_name = member_exported_name
                    elif alias_exported_name is not None:
                        export_kind = alias_export_kind
                        exported_name = alias_exported_name
                    func_info = self._create_function_info(
                        node, code, file_path, func_name, 'function',
                        current_classes, class_contexts, imports,
                        is_exported=is_exported, export_kind=export_kind,
                        exported_name=exported_name, member_name=member_name,
                        complexity=complexity, loc=loc, param_count=param_count,
                    )
                    if func_info:
                        functions.append(func_info)

                self._push_function_body_children(node, stack, current_classes, True)
                continue

            # ---------- 3. lexical_declaration（const/let） ----------
            if (
                node.type in ('lexical_declaration', 'variable_declaration')
                and not in_function_body
            ):
                for child in node.children:
                    if child.type != 'variable_declarator':
                        continue
                    var_name, init_node = self._get_declarator_name_and_init(child, code)
                    if not (var_name and init_node):
                        continue
                    if self._is_private_name(var_name):
                        continue
                    member_export_kind, member_exported_name, member_name = (
                        self._get_exported_object_member_metadata(
                            root_node, var_name, code
                        )
                    )
                    alias_export_kind, alias_exported_name = (
                        self._get_local_alias_export_metadata(
                            root_node, var_name, code
                        )
                    )
                    is_exported = (
                        var_name in exported_names
                        or member_name is not None
                        or alias_exported_name is not None
                    )
                    if self.only_exported and not is_exported:
                        continue
                    if init_node.type in CLASS_NODE_TYPES:
                        stack.append((init_node, current_classes, False))
                        continue
                    if init_node.type not in FUNCTION_VALUE_TYPES:
                        continue
                    # if init_node.type not in ('function', 'arrow_function'):
                    #     continue

                    full_code = code[node.start_byte:node.end_byte].decode('utf-8')
                    complexity, loc, param_count = self._compute_complexity_and_loc(
                        full_code, init_node, lizard_functions, var_name
                    )

                    if init_node.type == 'arrow_function':
                        is_async = self._is_async_arrow_function(init_node, code)
                    else:
                        is_async = self._is_async_function(init_node)

                    export_kind, exported_name = self._get_export_metadata(
                        root_node, init_node, var_name, code
                    )
                    if member_name is not None:
                        export_kind = member_export_kind
                        exported_name = member_exported_name
                    elif alias_exported_name is not None:
                        export_kind = alias_export_kind
                        exported_name = alias_exported_name
                    func_info = self._create_function_info(
                        init_node, code, file_path, var_name, 'function',
                        current_classes, class_contexts, imports,
                        is_async=is_async,
                        is_exported=is_exported,
                        code_override=full_code,
                        line_node_override=node,
                        complexity=complexity, loc=loc, param_count=param_count,
                        export_kind=export_kind,
                        exported_name=exported_name,
                        member_name=member_name,
                    )
                    if func_info:
                        functions.append(func_info)

                    # 标记函数体内部
                    # if init_node.type == 'function':
                    #     self._push_function_body_children(init_node, stack, current_classes, True)
                    # else:
                    #     for gc in reversed(init_node.children):
                    #         stack.append((gc, current_classes, True))
                    # 普通函数表达式和生成器函数使用函数体遍历逻辑；
                    # 箭头函数继续按现有逻辑遍历。
                    if init_node.type != 'arrow_function':
                        self._push_function_body_children(
                            init_node,
                            stack,
                            current_classes,
                            True,
                        )
                    else:
                        for gc in reversed(init_node.children):
                            stack.append((gc, current_classes, True))

                continue

            # ---------- 4. method_definition ----------
            if node.type == 'method_definition' and current_classes:
                # 排除 getter/setter，不将属性访问器作为独立测试目标
                if (
                    node.type == 'method_definition'
                    and current_classes
                    and self._is_getter_or_setter(node)
                ):
                    self._push_function_body_children(
                        node, stack, current_classes, True
                    )
                    continue
                class_is_exported = current_classes[-1] in exported_classes
                if self.only_exported and not class_is_exported:
                    self._push_function_body_children(node, stack, current_classes, True)
                    continue

                method_name = self._get_name(node, code)
                if (method_name
                        and method_name != 'constructor'
                        and not self._is_private_name(method_name)):
                    method_code = code[node.start_byte:node.end_byte].decode('utf-8')
                    complexity, loc, param_count = self._compute_complexity_and_loc(
                        method_code, node, lizard_functions, method_name
                    )

                    class_export_kind, class_exported_name = (
                        class_export_metadata.get(
                            current_classes[-1],
                            (None, None),
                        )
                    )
                    func_info = self._create_function_info(
                        node, code, file_path, method_name, 'method',
                        current_classes, class_contexts, imports,
                        is_exported=class_is_exported,
                        complexity=complexity, loc=loc, param_count=param_count,
                        class_export_kind=class_export_kind,
                        class_exported_name=class_exported_name
                    )
                    if func_info:
                        functions.append(func_info)

                self._push_function_body_children(node, stack, current_classes, True)
                continue

            # ---------- 5. class field arrow function ----------
            if node.type in ('field_definition', 'public_field_definition') \
                    and current_classes and not in_function_body:
                class_is_exported = current_classes[-1] in exported_classes
                if self.only_exported and not class_is_exported:
                    continue

                field_name = self._get_field_name(node, code)
                if field_name and not self._is_private_name(field_name):
                    for child in node.children:
                        if child.type == 'arrow_function':
                            field_code = code[node.start_byte:node.end_byte].decode('utf-8')
                            complexity, loc, param_count = self._compute_complexity_and_loc(
                                field_code, child, lizard_functions, field_name
                            )

                            class_export_kind, class_exported_name = (
                                class_export_metadata.get(
                                    current_classes[-1],
                                    (None, None),
                                )
                            )
                            func_info = self._create_function_info(
                                node, code, file_path, field_name, 'method',
                                current_classes, class_contexts, imports,
                                is_async=self._is_async_arrow_function(child, code),
                                is_exported=class_is_exported,
                                complexity=complexity, loc=loc, param_count=param_count,
                                class_export_kind=class_export_kind,
                                class_exported_name=class_exported_name
                            )
                            if func_info:
                                functions.append(func_info)

                            for gc in reversed(child.children):
                                stack.append((gc, current_classes, True))
                            break
                continue

            # ---------- 6. 顶层裸箭头函数赋值 ----------
            if node.type == 'arrow_function' and not current_classes and not in_function_body:
                func_name = self._get_ancestor_assignment_name(node, code)
                is_exported = bool(func_name and func_name in exported_names)
                if (func_name
                        and not self._is_private_name(func_name)
                        and (not self.only_exported or is_exported)):
                    assignment_node = self._find_assignment_expression(node)
                    src_node = assignment_node or node
                    full_code = code[src_node.start_byte:src_node.end_byte].decode('utf-8')
                    complexity, loc, param_count = self._compute_complexity_and_loc(
                        full_code, node, lizard_functions, func_name
                    )

                    export_kind, exported_name = self._get_export_metadata(
                        root_node, node, func_name, code
                    )

                    func_info = self._create_function_info(
                        node, code, file_path, func_name, 'function',
                        current_classes, class_contexts, imports,
                        is_async=self._is_async_arrow_function(node, code),
                        is_exported=is_exported,
                        export_kind=export_kind,
                        exported_name=exported_name,
                        code_override=full_code,
                        line_node_override=src_node,
                        complexity=complexity, loc=loc, param_count=param_count,
                    )
                    if func_info:
                        functions.append(func_info)

                    for child in reversed(node.children):
                        stack.append((child, current_classes, True))
                    continue

            # ---------- 7. 默认 ----------
            for child in reversed(node.children):
                stack.append((child, current_classes, in_function_body))

        return functions

    # ------------------------------------------------------------------
    # ★ 导出名单收集（ESM + CJS，兼容多种 tree-sitter 结构）
    # ------------------------------------------------------------------
    def _collect_exported_names(self, root_node, code) -> set:
        """
        收集文件里所有被导出的顶层名字。

        覆盖的 ESM 写法：
          - export function foo
          - export class Foo
          - export const foo = ...
          - export { foo, bar as baz }
          - export default foo
          - export default function bar / export default class Baz

        覆盖的 CJS 写法：
          - module.exports = { foo, bar }
          - module.exports.foo = ...
          - exports.foo = ...

        说明：
          - export { foo as bar } 同时收集 foo 和 bar，方便匹配函数名和下游理解
          - export * from '...' 跨文件，不处理
        """
        exported = set()

        def text_of(n):
            return code[n.start_byte:n.end_byte].decode('utf-8')

        def collect_export_clause(clause_node):
            """
            处理 export { ... }。

            兼容多种 tree-sitter-javascript 结构：
              A) clause 下直接是 identifier / property_identifier（旧版）
              B) clause 下是 export_specifier，其中含 1~2 个 identifier（新版，可能是 foo as bar）
              C) 极少数实现有额外的中间层节点
            """
            for spec in clause_node.children:
                if spec.type == 'export_specifier':
                    ids = [
                        x for x in self._walk_nodes(spec)
                        if x.type in ('identifier', 'property_identifier')
                    ]
                    if ids:
                        # 原名和别名都收
                        exported.add(text_of(ids[0]))
                        if len(ids) > 1:
                            exported.add(text_of(ids[-1]))

                elif spec.type in ('identifier', 'property_identifier'):
                    # 旧版直接挂 identifier
                    exported.add(text_of(spec))

                else:
                    # 兜底：某些版本可能在中间包了一层，递归扫一遍
                    for x in spec.children:
                        if x.type in ('identifier', 'property_identifier'):
                            exported.add(text_of(x))

        def traverse(node):
            # -------- ESM: export_statement --------
            if node.type == 'export_statement':
                statement_text = text_of(node).strip()
                # 跨文件 re-export（export { x as y } from './other.js'）
                # 只声明转发关系，不代表当前文件定义/导出了本地绑定。
                is_reexport = bool(re.match(
                    r"^\s*export\s*\{[\s\S]*\}\s*from\s*['\"]", statement_text
                ))
                is_default = any(c.type == 'default' for c in node.children)

                if is_default:
                    exported.add('default')
                    for c in node.children:
                        if c.type in FUNCTION_DECLARATION_TYPES:
                            n = self._get_name(c, code)
                            if n:
                                exported.add(n)
                        elif c.type == 'class_declaration':
                            n = self._get_class_name(c, code)
                            if n:
                                exported.add(n)
                        elif c.type == 'identifier':
                            exported.add(text_of(c))

                for c in node.children:
                    if c.type in FUNCTION_DECLARATION_TYPES:
                        n = self._get_name(c, code)
                        if n:
                            exported.add(n)
                    elif c.type == 'class_declaration':
                        n = self._get_class_name(c, code)
                        if n:
                            exported.add(n)
                    elif c.type in ('lexical_declaration', 'variable_declaration'):
                        for decl in c.children:
                            if decl.type == 'variable_declarator':
                                vn, _ = self._get_declarator_name_and_init(decl, code)
                                if vn:
                                    exported.add(vn)
                                # export const api = { normalize };
                                # export const api = { normalize: normalize };
                                # 对象属性暴露了本地绑定，因此该绑定可以通过
                                # api.normalize 从模块外部访问。
                                exported.update(
                                    self._get_exported_object_members(decl, code)
                                )
                    elif c.type == 'export_clause' and not is_reexport:
                        collect_export_clause(c)

            # -------- CJS: module.exports / exports.xxx --------
            if node.type == 'expression_statement':
                text = text_of(node).strip()

                # 1. module.exports = { foo, alias: localFn }
                # 同时收集属性名和右侧的本地绑定名
                object_match = re.match(
                    r'^module\.exports\s*=\s*\{([\s\S]*)\}\s*;?\s*$',
                    text
                )

                if object_match:
                    body = object_match.group(1)

                    # 适用于简单对象导出；复杂嵌套对象建议进一步改为 AST 解析
                    for item in body.split(','):
                        item = item.strip()
                        if not item:
                            continue

                        if ':' in item:
                            key, value = item.split(':', 1)
                            key = key.strip().strip("'\"")
                            value = value.strip()

                            if re.fullmatch(r'[A-Za-z_$][\w$]*', key):
                                exported.add(key)

                            # alias: localFn -> 同时记录 localFn
                            if re.fullmatch(r'[A-Za-z_$][\w$]*', value):
                                exported.add(value)
                        else:
                            # shorthand: { foo }
                            name = item.strip()

                            if re.fullmatch(r'[A-Za-z_$][\w$]*', name):
                                exported.add(name)

                # 2. module.exports = localFn
                # 导出的是已有函数或变量
                direct_match = re.match(
                    r'^module\.exports\s*=\s*([A-Za-z_$][\w$]*)\s*;?\s*$',
                    text
                )

                if direct_match:
                    exported.add(direct_match.group(1))

                # 3. module.exports.foo = ... / exports.foo = ...
                # 收集公开属性名
                for pattern in (
                    r'\bmodule\.exports\.([A-Za-z_$][\w$]*)\s*=',
                    r'\bexports\.([A-Za-z_$][\w$]*)\s*=',
                    r"\bmodule\.exports\s*\[\s*['\"]([A-Za-z_$][\w$]*)['\"]\s*\]\s*=",
                    r"\bexports\s*\[\s*['\"]([A-Za-z_$][\w$]*)['\"]\s*\]\s*=",
                ):
                    for match in re.finditer(pattern, text):
                        exported.add(match.group(1))

                # 4. 属性赋值右侧是已有本地函数
                # exports.publicName = localFn
                alias_match = re.search(
                    r'\b(?:module\s*\.\s*exports'
                    r'(?:\s*\.\s*[A-Za-z_$][\w$]*'
                    r'|\s*\[\s*[\'\"][A-Za-z_$][\w$]*[\'\"]\s*\])?'
                    r'|exports(?:\s*\.\s*[A-Za-z_$][\w$]*'
                    r'|\s*\[\s*[\'\"][A-Za-z_$][\w$]*[\'\"]\s*\]))'
                    r'\s*=\s*([A-Za-z_$][\w$]*)\s*;?\s*$',
                    text
                )

                if alias_match:
                    exported.add(alias_match.group(1))

                # Object.defineProperty(exports, 'foo', { value: foo })
                define_property = re.search(
                    r'Object\.defineProperty\s*\(\s*'
                    r'(?:exports|module\.exports)\s*,\s*'
                    r'([\'\"])([A-Za-z_$][\w$]*)\1\s*,\s*'
                    r'\{[\s\S]*?\bvalue\s*:\s*([A-Za-z_$][\w$]*)',
                    text,
                )
                if define_property:
                    exported.add(define_property.group(2))
                    exported.add(define_property.group(3))

                # 5. module.exports = function () {} / module.exports = (...) => ...
                # 匿名函数没有本地绑定名，统一加入 default
                if re.match(
                    r'^module\.exports\s*=\s*(?:(?:async)\s+)?function\b',
                    text
                ) or re.match(
                    r'^module\.exports\s*=\s*(?:async\s+)?'
                    r'(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>',
                    text
                ):
                    exported.add('default')

            for child in node.children:
                traverse(child)

        traverse(root_node)
        return exported

    def _get_exported_object_members(self, declarator_node, code) -> set:
        """收集导出对象字面量中引用的本地绑定名。"""
        object_node = next(
            (child for child in declarator_node.children if child.type == 'object'),
            None,
        )
        if object_node is None:
            return set()

        members = set()
        for child in object_node.children:
            if child.type == 'shorthand_property_identifier':
                members.add(code[child.start_byte:child.end_byte].decode('utf-8'))
            elif child.type == 'pair':
                # Only a bare local identifier value (e.g. { clean: normalize })
                # represents a local binding. Do not mistake identifiers inside
                # member expressions (e.g. { foo: other.foo }) for local functions.
                value_node = child.child_by_field_name('value')
                if value_node is None:
                    named_children = [item for item in child.children if item.is_named]
                    if len(named_children) >= 2:
                        value_node = named_children[-1]
                if value_node is not None and value_node.type == 'identifier':
                    members.add(
                        code[value_node.start_byte:value_node.end_byte].decode('utf-8')
                    )
        return members

    def _get_export_metadata(self, root_node, target_node, local_name, code):
        """
        获取函数的导出元数据。

        Returns:
            (export_kind, exported_name)

        name 由调用方根据真实函数声明决定。
        匿名默认导出的 exported_name 为 None。

        支持：
            ESM:
                export function foo() {}
                export const foo = () => {}
                export default function () {}
                export default foo
                export { foo }
                export { foo as bar }

            CommonJS:
                module.exports = foo
                module.exports.foo = foo
                exports.foo = foo
                module.exports = { foo, bar: foo }
        """

        def text_of(node):
            return code[node.start_byte:node.end_byte].decode(
                'utf-8', errors='replace'
            )

        # --------------------------------------------------------------
        # 1. 检查目标函数是否直接位于 ESM export_statement 中
        # --------------------------------------------------------------
        current = target_node

        while current is not None:
            if current.type == 'export_statement':
                is_default = any(
                    child.type == 'default'
                    for child in current.children
                )

                if is_default:
                    return 'esm_default', None

                if local_name:
                    return 'esm_named', local_name

            current = current.parent

        # --------------------------------------------------------------
        # 2. 检查文件中其他位置的 ESM 导出声明
        #    例如：function foo() {}
        #          export { foo as bar };
        # --------------------------------------------------------------
        for node in self._walk_nodes(root_node):
            if node.type != 'export_statement':
                continue

            statement_text = text_of(node).strip()

            is_default = any(
                child.type == 'default'
                for child in node.children
            )

            # export default foo;
            if is_default:
                if local_name:
                    for child in node.children:
                        if (
                            child.type == 'identifier'
                            and text_of(child) == local_name
                        ):
                            return 'esm_default', None

                continue

            # 跳过跨文件重新导出：
            # export { foo as bar } from './other.js';
            # 它不能直接证明当前文件中的 foo 是该导出的来源。
            is_reexport = re.match(
                r"""^\s*export\s*\{[\s\S]*\}\s*from\s*['"]""",
                statement_text,
            )

            if is_reexport:
                continue

            # ----------------------------------------------------------
            # 2.1 使用源码文本兼容不同 AST 节点结构
            #     export { foo as bar };
            #     export { foo };
            # ----------------------------------------------------------
            clause_match = re.fullmatch(
                r'\s*export\s*\{([^}]*)\}\s*;?\s*',
                statement_text,
                re.DOTALL,
            )

            if clause_match and local_name:
                for item in clause_match.group(1).split(','):
                    item = item.strip()

                    match = re.fullmatch(
                        r'(?P<local>[A-Za-z_$][\w$]*)'
                        r'(?:\s+as\s+(?P<public>[A-Za-z_$][\w$]*))?',
                        item,
                    )

                    if not match:
                        continue

                    original_name = match.group('local')
                    public_name = match.group('public') or original_name

                    if original_name == local_name:
                        return 'esm_named', public_name

            # ----------------------------------------------------------
            # 2.2 保留基于 AST 的导出列表识别
            # ----------------------------------------------------------
            for clause in node.children:
                if clause.type != 'export_clause':
                    continue

                for spec in clause.children:
                    if spec.type == 'export_specifier':
                        identifiers = [
                            item
                            for item in self._walk_nodes(spec)
                            if item.type in (
                                'identifier',
                                'property_identifier',
                            )
                        ]

                        if identifiers and local_name:
                            original_name = text_of(identifiers[0])
                            public_name = text_of(identifiers[-1])

                            if original_name == local_name:
                                return 'esm_named', public_name

                    elif (
                        spec.type in ('identifier', 'property_identifier')
                        and local_name
                        and text_of(spec) == local_name
                    ):
                        return 'esm_named', local_name

        # --------------------------------------------------------------
        # 3. 检查 CommonJS 导出
        # --------------------------------------------------------------
        if local_name:
            escaped_name = re.escape(local_name)

            for node in self._walk_nodes(root_node):
                if node.type != 'expression_statement':
                    continue

                statement = text_of(node).strip()

                # ------------------------------------------------------
                # 3.1 module.exports = foo;
                # ------------------------------------------------------
                direct_match = re.fullmatch(
                    r'module\s*\.\s*exports\s*=\s*'
                    + escaped_name
                    + r'\s*;?',
                    statement,
                )

                if direct_match:
                    return 'commonjs_default', None

                # ------------------------------------------------------
                # 3.2 exports.bar = foo;
                #     module.exports.bar = foo;
                # ------------------------------------------------------
                property_match = re.search(
                    r'\b(?:module\s*\.\s*exports|exports)'
                    r'(?:\s*\.\s*([A-Za-z_$][\w$]*)|'
                    r'\s*\[\s*([\'\"])([A-Za-z_$][\w$]*)\2\s*\])'
                    r'\s*=\s*'
                    + escaped_name
                    + r'\s*;?\s*$',
                    statement,
                )

                if property_match:
                    return 'commonjs_named', (
                        property_match.group(1) or property_match.group(3)
                    )

                define_property = re.search(
                    r'Object\.defineProperty\s*\(\s*'
                    r'(?:exports|module\.exports)\s*,\s*'
                    r'([\'\"])([A-Za-z_$][\w$]*)\1\s*,\s*'
                    r'\{[\s\S]*?\bvalue\s*:\s*'
                    + escaped_name,
                    statement,
                )
                if define_property:
                    return 'commonjs_named', define_property.group(2)

                # ------------------------------------------------------
                # 3.3 module.exports = { foo, bar: foo };
                #     兼容简单对象属性与别名
                # ------------------------------------------------------
                object_match = re.fullmatch(
                    r'module\s*\.\s*exports\s*=\s*'
                    r'\{([\s\S]*)\}\s*;?',
                    statement,
                )

                if object_match:
                    for item in object_match.group(1).split(','):
                        item = item.strip()

                        if not item:
                            continue

                        if ':' in item:
                            key, value = item.split(':', 1)
                            key = key.strip().strip("'\"")
                            value = value.strip()
                        else:
                            # 简写属性：{ foo }
                            key = value = item

                        if value == local_name:
                            return 'commonjs_named', key

        # --------------------------------------------------------------
        # 4. ESM 导出对象中的本地函数引用
        #    export const api = { normalize };
        #    export const api = { normalize: normalize };
        # --------------------------------------------------------------
        if local_name:
            for node in self._walk_nodes(root_node):
                if node.type != 'export_statement':
                    continue
                for child in node.children:
                    if child.type not in ('lexical_declaration', 'variable_declaration'):
                        continue
                    for decl in child.children:
                        if decl.type != 'variable_declarator':
                            continue
                        container_name, _ = self._get_declarator_name_and_init(
                            decl, code
                        )
                        if (
                            container_name
                            and local_name in self._get_exported_object_members(
                                decl, code
                            )
                        ):
                            return 'esm_named', container_name

        # --------------------------------------------------------------
        # 5. 没有找到匹配的导出关系
        # --------------------------------------------------------------
        return None, None


    def _get_exported_object_member_metadata(self, root_node, local_name, code):
        """查找本地函数绑定通过导出对象公开时的属性元数据。

        例如：
            function normalize(value) {}
export const api = { normalize };
            function normalize(value) {}
const api = { normalize: normalize };
export { api as publicApi };
            function normalize(value) {}
module.exports = { normalize };

        返回 (export_kind, exported_name, member_name)。这里的 name 仍由函数
        声明/变量声明确定；member_name 表示对象上的公开属性名。
        """
        if not local_name:
            return None, None, None

        def text_of(node):
            return code[node.start_byte:node.end_byte].decode(
                'utf-8', errors='replace'
            ).strip()

        def is_module_level(node):
            current = node
            while current is not None:
                if current.type == 'program':
                    return True
                if current.type in {
                    'statement_block', 'function_declaration',
                    'generator_function_declaration', 'function',
                    'function_expression', 'generator_function',
                    'arrow_function', 'method_definition', 'class_body',
                }:
                    return False
                current = current.parent
            return False

        def property_name(node):
            if node is None:
                return None
            if node.type in ('identifier', 'property_identifier'):
                return text_of(node)
            if node.type in ('string', 'string_fragment'):
                value = text_of(node)
                if len(value) >= 2 and value[0] in ('\'', '"', '`') and value[-1] == value[0]:
                    return value[1:-1]
            return None

        def object_export_info(obj):
            """返回 (kind, public_container_name)，非导出对象返回 None。"""
            parent = obj.parent

            # export const api = Object.freeze({ foo });
            # export const api = Object.assign({}, { foo });
            # 将常见的对象包装调用视为透明容器。
            ancestor = parent
            through_call = False
            while ancestor is not None:
                if ancestor.type == 'call_expression':
                    through_call = True
                if ancestor.type == 'variable_declarator' and through_call:
                    var_name, _ = self._get_declarator_name_and_init(ancestor, code)
                    if var_name:
                        kind, exported_name = self._get_export_metadata(
                            root_node, obj, var_name, code
                        )
                        if kind == 'esm_named':
                            return 'esm_named_object', exported_name or var_name
                        if kind == 'esm_default':
                            return 'esm_default_object', None
                        if kind == 'commonjs_named':
                            return 'commonjs_named_object', exported_name
                        if kind == 'commonjs_default':
                            return 'commonjs_default_object', None
                    break
                if ancestor.type in ('program', 'statement_block'):
                    break
                ancestor = ancestor.parent

            # module.exports = { ... } 或 exports.api = { ... }
            if parent is not None and parent.type == 'assignment_expression':
                right = parent.child_by_field_name('right')
                left = parent.child_by_field_name('left')
                if (right is None or left is None
                        or right.start_byte != obj.start_byte
                        or right.end_byte != obj.end_byte):
                    return None

                left_text = re.sub(r'\s+', '', text_of(left))
                if left_text == 'module.exports':
                    # 根导出对象中的成员本身就是模块公开属性。
                    return 'commonjs_root_object', None
                match = re.fullmatch(
                    r'(?:module\.exports|exports)\.([A-Za-z_$][\w$]*)',
                    left_text,
                )
                if match:
                    return 'commonjs_named_object', match.group(1)
                return None

            # export default { ... }
            if parent is not None and parent.type == 'export_statement':
                if any(child.type == 'default' for child in parent.children):
                    return 'esm_default_object', None
                return None

            # const api = { ... }; export { api as publicApi };
            # export const api = { ... };
            # const api = { ... }; module.exports = api;
            if parent is not None and parent.type == 'variable_declarator':
                var_name, _ = self._get_declarator_name_and_init(parent, code)
                if not var_name:
                    return None
                kind, exported_name = self._get_export_metadata(
                    root_node, obj, var_name, code
                )
                if kind == 'esm_named':
                    return 'esm_named_object', exported_name or var_name
                if kind == 'esm_default':
                    return 'esm_default_object', None
                if kind == 'commonjs_named':
                    return 'commonjs_named_object', exported_name
                if kind == 'commonjs_default':
                    return 'commonjs_default_object', None
            return None

        def iter_members(object_node, prefix=''):
            for member in object_node.children:
                member_name = None
                binding_name = None
                value_node = None

                if member.type == 'shorthand_property_identifier':
                    binding_name = text_of(member)
                    member_name = binding_name
                elif member.type == 'pair':
                    key_node = member.child_by_field_name('key')
                    value_node = member.child_by_field_name('value')
                    named = [child for child in member.children if child.is_named]
                    if key_node is None and named:
                        key_node = named[0]
                    if value_node is None and len(named) >= 2:
                        value_node = named[-1]
                    member_name = property_name(key_node)
                    if value_node is not None and value_node.type == 'identifier':
                        binding_name = text_of(value_node)

                if member_name:
                    full_name = f'{prefix}{member_name}'
                    if binding_name:
                        yield binding_name, full_name
                    if value_node is not None and value_node.type == 'object':
                        yield from iter_members(value_node, full_name + '.')

        for obj in self._walk_nodes(root_node):
            if obj.type != 'object' or not is_module_level(obj):
                continue

            export_info = object_export_info(obj)
            if export_info is None:
                continue
            mode, container_name = export_info

            for binding_name, member_name in iter_members(obj):
                if binding_name != local_name:
                    continue
                if self._is_private_name(member_name):
                    continue

                if mode == 'commonjs_root_object':
                    return 'commonjs_named', member_name, member_name
                if mode == 'commonjs_named_object':
                    return 'commonjs_named', container_name, member_name
                if mode == 'esm_named_object':
                    return 'esm_named', container_name, member_name
                if mode == 'esm_default_object':
                    return 'esm_default', None, member_name
                if mode == 'commonjs_default_object':
                    return 'commonjs_default', None, member_name

        return None, None, None

    def _get_local_alias_export_metadata(self, root_node, local_name, code):
        """解析 ``const publicName = localName; export { publicName }``。"""
        if not local_name:
            return None, None

        exported_names = self._collect_exported_names(root_node, code)
        for node in self._walk_nodes(root_node):
            if node.type not in ('lexical_declaration', 'variable_declaration'):
                continue
            for decl in node.children:
                if decl.type != 'variable_declarator':
                    continue
                children = [child for child in decl.children if child.is_named]
                if len(children) < 2:
                    continue
                alias_node, value_node = children[0], children[-1]
                if alias_node.type != 'identifier' or value_node.type != 'identifier':
                    continue
                alias = code[alias_node.start_byte:alias_node.end_byte].decode('utf-8')
                value = code[value_node.start_byte:value_node.end_byte].decode('utf-8')
                if value != local_name or alias not in exported_names:
                    continue
                kind, public_name = self._get_export_metadata(
                    root_node, alias_node, alias, code
                )
                return kind or 'esm_named', public_name or alias
        return None, None

    def _extract_exported_object_functions(
        self, root_node, code, file_path, class_contexts, imports,
        lizard_functions,
    ):
        """提取模块导出对象中直接定义的公有函数和方法。"""

        results = []
        seen = set()

        def text_of(node):
            return code[node.start_byte:node.end_byte].decode(
                "utf-8", errors="replace"
            )

        def is_module_level(node):
            current = node
            while current is not None:
                if current.type == "program":
                    return True
                if current.type in {
                    "statement_block", "function_declaration",
                    "generator_function_declaration", "function",
                    "function_expression", "generator_function",
                    "arrow_function", "method_definition", "class_body",
                }:
                    return False
                current = current.parent
            return False

        def property_name(node):
            if node is None:
                return None

            if node.type in ("identifier", "property_identifier"):
                return text_of(node).strip()

            if node.type in ("string", "string_fragment"):
                value = text_of(node).strip()
                if len(value) >= 2 and value[0] in ("'", '"', "`"):
                    if value[-1] == value[0]:
                        return value[1:-1]

            # 动态计算属性暂不处理
            return None

        def get_members(object_node, prefix=''):
            """返回 (函数节点, 源码节点, 属性名, 真实函数名)。"""
            for member in object_node.children:

                # 对象方法：foo() {}
                if member.type == "method_definition":
                    # 对象字面量中的 getter/setter 同样不作为测试候选
                    if self._is_getter_or_setter(member):
                        continue

                    member_name = self._get_name(member, code)
                    if member_name:
                        public_name = f'{prefix}{member_name}'
                        yield member, member, public_name, member_name
                    continue

                # 函数值：foo: function() {} 或 foo: (x) => x
                if member.type != "pair":
                    continue

                key_node = member.child_by_field_name("key")
                value_node = member.child_by_field_name("value")

                named = [c for c in member.children if c.is_named]
                if key_node is None and named:
                    key_node = named[0]
                if value_node is None and len(named) >= 2:
                    value_node = named[-1]

                member_name = property_name(key_node)
                if not member_name or value_node is None:
                    continue

                public_name = f'{prefix}{member_name}'
                if value_node.type == 'object':
                    yield from get_members(value_node, public_name + '.')
                    continue

                if value_node.type not in FUNCTION_VALUE_TYPES:
                    continue

                func_name = (
                    None if value_node.type == "arrow_function"
                    else self._get_name(value_node, code)
                )
                yield value_node, member, public_name, func_name

        for obj in self._walk_nodes(root_node):
            if obj.type != "object" or not is_module_level(obj):
                continue

            parent = obj.parent
            mode = None
            container_name = None

            # module.exports = { ... }
            # exports.api = { ... }
            # module.exports.api = { ... }
            if parent is not None and parent.type == "assignment_expression":
                right = parent.child_by_field_name("right")
                left = parent.child_by_field_name("left")

                if (
                    right is None or left is None
                    or right.start_byte != obj.start_byte
                    or right.end_byte != obj.end_byte
                ):
                    continue

                left_text = re.sub(r"\s+", "", text_of(left))

                if left_text == "module.exports":
                    mode = "commonjs_root_object"
                else:
                    match = re.fullmatch(
                        r"(?:module\.exports|exports)\.([A-Za-z_$][\w$]*)",
                        left_text,
                    )
                    if match:
                        mode = "commonjs_nested_object"
                        container_name = match.group(1)

            # export default { ... }
            elif parent is not None and parent.type == "export_statement":
                if any(c.type == "default" for c in parent.children):
                    mode = "esm_default_object"

            # const api = { ... }; export { api as publicApi };
            # export const api = { ... };
            # const api = { ... }; module.exports = api;
            elif parent is not None and parent.type == "variable_declarator":
                var_name, _ = self._get_declarator_name_and_init(parent, code)
                if not var_name:
                    continue

                kind, exported_name = self._get_export_metadata(
                    root_node, obj, var_name, code
                )

                if kind == "commonjs_default":
                    mode = "commonjs_root_object"
                elif kind == "commonjs_named":
                    mode = "commonjs_nested_object"
                    container_name = exported_name
                elif kind == "esm_default":
                    mode = "esm_default_object"
                elif kind == "esm_named":
                    mode = "esm_named_object"
                    container_name = exported_name

            # export const api = Object.freeze({ foo });
            # export const api = Object.assign({}, { foo });
            if mode is None:
                ancestor = parent
                through_call = False
                while ancestor is not None:
                    if ancestor.type == "call_expression":
                        through_call = True
                    if ancestor.type == "variable_declarator" and through_call:
                        var_name, _ = self._get_declarator_name_and_init(
                            ancestor, code
                        )
                        if var_name:
                            kind, exported_name = self._get_export_metadata(
                                root_node, obj, var_name, code
                            )
                            if kind == "esm_named":
                                mode = "esm_named_object"
                                container_name = exported_name or var_name
                            elif kind == "esm_default":
                                mode = "esm_default_object"
                            elif kind == "commonjs_named":
                                mode = "commonjs_nested_object"
                                container_name = exported_name
                            elif kind == "commonjs_default":
                                mode = "commonjs_root_object"
                        break
                    if ancestor.type in ("program", "statement_block"):
                        break
                    ancestor = ancestor.parent

            if mode is None:
                continue

            for func_node, source_node, member_name, func_name in get_members(obj):
                key = (func_node.start_byte, func_node.end_byte)
                if key in seen:
                    continue
                seen.add(key)

                if self._is_private_name(member_name):
                    continue

                # module.exports = { foo() {} }
                # require(module).foo()，故 foo 是具名公开属性。
                if mode == "commonjs_root_object":
                    export_kind = "commonjs_named"
                    exported_name = member_name
                    output_member_name = member_name

                elif mode == "commonjs_nested_object":
                    export_kind = "commonjs_named"
                    exported_name = container_name
                    output_member_name = member_name

                elif mode == "esm_named_object":
                    export_kind = "esm_named"
                    exported_name = container_name
                    output_member_name = member_name

                else:
                    export_kind = "esm_default"
                    exported_name = None
                    output_member_name = member_name

                source_code = text_of(source_node)
                complexity, loc, param_count = (
                    self._compute_complexity_and_loc(
                        source_code, func_node, lizard_functions, func_name
                    )
                )

                is_async = (
                    self._is_async_arrow_function(func_node, code)
                    if func_node.type == "arrow_function"
                    else self._is_async_function(func_node)
                )

                info = self._create_function_info(
                    func_node, code, file_path, func_name, "object_method",
                    [], class_contexts, imports,
                    is_async=is_async,
                    is_exported=True,
                    code_override=source_code,
                    line_node_override=source_node,
                    export_kind=export_kind,
                    exported_name=exported_name,
                    member_name=output_member_name,
                    complexity=complexity,
                    loc=loc,
                    param_count=param_count,
                )
                results.append(info)

        return results
    
    # ------------------------------------------------------------------
    # import 提取（ESM + CJS）
    # ------------------------------------------------------------------
    def _extract_imports(self, root_node, code) -> List[str]:
        imports = []

        def traverse(node):
            if node.type in ('import_statement', 'import_declaration'):
                imports.append(node.text.decode('utf-8').strip())
            elif node.type == 'lexical_declaration':
                text = node.text.decode('utf-8').strip()
                if 'require(' in text:
                    imports.append(text)
            for child in node.children:
                traverse(child)

        traverse(root_node)
        return list(dict.fromkeys(imports))

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    # def _get_declarator_name_and_init(self, declarator_node, code):
    #     var_name = None
    #     init_node = None

    #     for child in declarator_node.children:
    #         if child.type == 'identifier':
    #             var_name = code[child.start_byte:child.end_byte].decode('utf-8')
    #         elif child.type in ('function', 'arrow_function'):
    #             init_node = child

    #     if not init_node:
    #         for i, child in enumerate(declarator_node.children):
    #             if child.type == '=' and i + 1 < len(declarator_node.children):
    #                 next_node = declarator_node.children[i + 1]
    #                 if next_node.type in ('function', 'arrow_function'):
    #                     init_node = next_node
    #                 break

    #     return var_name, init_node

    def _get_declarator_name_and_init(self, declarator_node, code):
        var_name = None
        init_node = None

        def is_class_expression(node):
            # 兼容当前解析器返回的 class 节点。
            # 必须包含 class_body，避免把 class 关键字叶节点误判为类。
            return (
                node.type == 'class_expression'
                or (
                    node.type == 'class'
                    and any(child.type == 'class_body' for child in node.children)
                )
            )

        function_value_types = FUNCTION_VALUE_TYPES

        for child in declarator_node.children:
            if child.type == 'identifier':
                var_name = code[
                    child.start_byte:child.end_byte
                ].decode('utf-8')

            elif child.type in function_value_types or is_class_expression(child):
                init_node = child

        # 兼容初始化节点未作为直接子节点识别的情况
        if init_node is None:
            children = declarator_node.children

            for i, child in enumerate(children):
                if child.type != '=' or i + 1 >= len(children):
                    continue

                candidate = children[i + 1]

                if (
                    candidate.type in function_value_types
                    or is_class_expression(candidate)
                ):
                    init_node = candidate

                break

        return var_name, init_node

    def _is_private_name(self, name):
        if not isinstance(name, str):
            return False
        return name.startswith('_') or name.startswith('#')

    # def _get_class_name(self, class_node, code):
    #     for child in class_node.children:
    #         if child.type == 'identifier':
    #             return code[child.start_byte:child.end_byte].decode('utf-8')
    #     return None

    def _get_class_name(self, class_node, code):
        # 优先获取类节点自身的名称
        for child in class_node.children:
            if child.type == 'identifier':
                return code[child.start_byte:child.end_byte].decode('utf-8')

        # 匿名类表达式：尝试从变量声明中获取绑定名称
        parent = class_node.parent

        if parent and parent.type == 'variable_declarator':
            for child in parent.children:
                if child.type == 'identifier':
                    return code[child.start_byte:child.end_byte].decode('utf-8')

        return None

    def _get_name(self, node, code):
        for child in node.children:
            if child.type in ('identifier', 'property_identifier'):
                return code[child.start_byte:child.end_byte].decode('utf-8')
        return None

    def _is_getter_or_setter(self, method_node) -> bool:
        """
        判断是否为 JavaScript getter/setter 访问器。

        只识别语法层面的 get/set 修饰符；
        不会排除普通的 get() 或 set() 方法。
        """
        if method_node.type != 'method_definition':
            return False

        return any(
            child.type in {'get', 'set'}
            for child in method_node.children
        )

    def _get_field_name(self, field_node, code):
        for child in field_node.children:
            if child.type == 'property_identifier':
                field_name = code[child.start_byte:child.end_byte].decode('utf-8')
                if field_name and not field_name.startswith('_') and not field_name.startswith('#'):
                    return field_name
        return None

    def _extract_field_name(self, field_node, code):
        return self._get_field_name(field_node, code)

    def _is_default_export_node(self, node):
        parent = node.parent

        return (
            parent is not None
            and parent.type == 'export_statement'
            and any(child.type == 'default' for child in parent.children)
        )

    def _get_cjs_assignment_export_name(self, node, code):
        # 寻找包含该函数节点的 assignment_expression
        assignment = node.parent

        while assignment and assignment.type != 'assignment_expression':
            if assignment.type in {
                'program',
                'expression_statement',
                'statement_block',
                'export_statement',
            }:
                return None

            assignment = assignment.parent

        if assignment is None:
            return None

        left = assignment.child_by_field_name('left')
        right = assignment.child_by_field_name('right')

        if left is None or right is None:
            return None

        # 仅识别直接赋值的函数，不把调用参数中的回调误当成导出函数
        candidate = right

        while candidate.type == 'parenthesized_expression':
            named_children = [
                child for child in candidate.children if child.is_named
            ]

            if len(named_children) != 1:
                return None

            candidate = named_children[0]

        if (
            candidate.start_byte != node.start_byte
            or candidate.end_byte != node.end_byte
        ):
            return None

        left_text = code[left.start_byte:left.end_byte].decode(
            'utf-8'
        ).strip()

        # module.exports.foo = function ...
        # exports.foo = () => ...
        if re.fullmatch(
            r'(?:exports|module\s*\.\s*exports)'
            r'(?:\s*\.\s*[A-Za-z_$][\w$]*|'
            r'\s*\[\s*[\'\"][A-Za-z_$][\w$]*[\'\"]\s*\])',
            left_text
        ):
            match = re.search(r'\.\s*([A-Za-z_$][\w$]*)\s*$', left_text)
            if match:
                return match.group(1)
            match = re.search(
                r'\[\s*[\'\"]([A-Za-z_$][\w$]*)[\'\"]\s*\]$',
                left_text,
            )
            return match.group(1) if match else None

        # module.exports = function ... is the CommonJS root/default export.
        # By contrast, exports.default = function ... is a named property export.
        if re.fullmatch(r'module\s*\.\s*exports', left_text):
            return COMMONJS_DEFAULT_EXPORT

        return None

    def _get_ancestor_assignment_name(self, node, code):
        parent = node.parent
        while parent:
            if parent.type == 'assignment_expression':
                for child in parent.children:
                    if child.type == 'identifier':
                        return code[child.start_byte:child.end_byte].decode('utf-8')
            parent = parent.parent
        return None

    def _find_assignment_expression(self, node):
        current = node.parent
        while current:
            if current.type == 'assignment_expression':
                return current
            current = current.parent
        return None

    def _is_async_function(self, func_node):
        for child in func_node.children:
            if child.type == 'async':
                return True
        return False

    def _is_async_arrow_function(self, node, code):
        if node.type == 'arrow_function':
            for child in node.children:
                if child.type == 'async':
                    return True
        elif node.type in ('field_definition', 'public_field_definition'):
            for child in node.children:
                if child.type == 'arrow_function':
                    return self._is_async_arrow_function(child, code)
        return False

    # ------------------------------------------------------------------
    # 类信息
    # ------------------------------------------------------------------
    def _extract_all_class_info(self, root_node, code, file_path):
        class_contexts = {}
        stack = [root_node]
        while stack:
            node = stack.pop()
            if node.type in CLASS_NODE_TYPES:
                class_info = self._extract_class_info(node, code, file_path)
                if class_info is None and self._get_cjs_assignment_export_name(node, code):
                    class_info = self._extract_class_info(
                        node, code, file_path, forced_name=ANONYMOUS_DEFAULT_CLASS
                    )
                if class_info and class_info['name']:
                    class_contexts[class_info['name']] = class_info
            for child in node.children:
                stack.append(child)
        return class_contexts

    def _extract_class_info(self, class_node, code, file_path, forced_name=None):
        class_info = {
            'name': '',
            'constructor': [],
            'fields': [],
        }
        class_name = forced_name or self._get_class_name(class_node, code)

        # 匿名默认导出类：使用内部标识关联构造函数、字段和方法
        if not class_name and self._is_default_export_node(class_node):
            class_name = ANONYMOUS_DEFAULT_CLASS

        if not class_name:
            return None

        class_info['name'] = class_name

        class_body = None
        for child in class_node.children:
            if child.type == 'class_body':
                class_body = child
                break
        if not class_body:
            return class_info

        for child in class_body.children:
            if child.type == 'method_definition':
                method_name = self._get_name(child, code)
                if method_name == 'constructor':
                    class_info['constructor'].append(
                        code[child.start_byte:child.end_byte].decode('utf-8')
                    )
            elif child.type in ('field_definition', 'public_field_definition'):
                field_name = self._extract_field_name(child, code)
                if field_name:
                    class_info['fields'].append(
                        code[child.start_byte:child.end_byte].decode('utf-8')
                    )
        return class_info

    # ------------------------------------------------------------------
    # 函数信息构造
    # ------------------------------------------------------------------
    def _create_function_info(
        self,
        func_node,
        code,
        file_path,
        func_name,
        func_type,
        class_stack,
        class_contexts,
        imports,
        is_async=None,
        is_arrow_method=False,
        is_exported=False,
        code_override=None,
        line_node_override=None,
        export_kind=None,
        exported_name=None,
        class_export_kind=None,
        class_exported_name=None,
        member_name=None,
        **kwargs,
    ):
        complexity = kwargs.get('complexity', 1)
        loc = kwargs.get('loc', 0)
        param_count = kwargs.get('param_count', 0)
        outgoing_degree = self._compute_outgoing_degree(func_node)

        func_code = code_override if code_override is not None \
            else code[func_node.start_byte:func_node.end_byte].decode('utf-8')

        if is_async is None:
            if func_node.type == 'arrow_function' or is_arrow_method:
                is_async = self._is_async_arrow_function(func_node, code)
            else:
                is_async = self._is_async_function(func_node)

        line_node = line_node_override or func_node
        start_line = line_node.start_point[0] + 1
        end_line = line_node.end_point[0] + 1

        formal_parameters = func_node.child_by_field_name('parameters')
        has_variadic_params = bool(formal_parameters and any(
            n.type in {'rest_pattern', 'spread_parameter'}
            for n in self._walk_nodes(formal_parameters)
        ))

        # 匿名导出函数没有真实函数名，测试文件使用稳定的备用名称。
        test_func_name = func_name or member_name

        if not test_func_name:
            if export_kind in ('esm_default', 'commonjs_default'):
                test_func_name = 'default_export'
            else:
                test_func_name = exported_name or 'anonymous_export'

        func_info = {
            'name': func_name,
            'export_kind': export_kind,
            'exported_name': exported_name,
            'src_file': os.path.relpath(file_path, self.project_root),
            'test_file': self._find_test_file(file_path, test_func_name),
            'code': func_code,
            'is_async': is_async,
            'is_exported': is_exported,
            'type': func_type,
            'complexity': complexity,
            'loc': loc,
            'outgoing_degree': outgoing_degree,
            'start_line': start_line,
            'end_line': end_line,
            'imports': imports,
            'has_variadic_params': has_variadic_params,
        }

        if member_name is not None:
            func_info["member_name"] = member_name

        if class_stack:
            internal_class_name = class_stack[-1]
            is_anonymous_default_class = (
                internal_class_name == ANONYMOUS_DEFAULT_CLASS
            )

            ctx = class_contexts.get(internal_class_name, {})

            # 内部标识绝不作为真实源码类名输出
            output_class_name = (
                None if is_anonymous_default_class else internal_class_name
            )

            output_class_hierarchy = [
                None if name == ANONYMOUS_DEFAULT_CLASS else name
                for name in class_stack
            ]

            output_full_class_name = (
                None if is_anonymous_default_class
                else '.'.join(class_stack)
            )

            func_info.update({
                'class_hierarchy': output_class_hierarchy,
                'class_name': output_class_name,
                'full_class_name': output_full_class_name,
                'class_constructor': ctx.get('constructor', []) or [],
                'class_fields': ctx.get('fields', []) or [],
                'class_is_anonymous': is_anonymous_default_class,
                'class_export_kind': class_export_kind,
                'class_exported_name': class_exported_name,
            })

        return func_info

    def _walk_nodes(self, node):
        stack = [node]
        while stack:
            current = stack.pop()
            yield current
            stack.extend(current.children)

    def _push_function_body_children(self, func_node, stack, current_classes, in_body_status):
        for child in func_node.children:
            if child.type == 'statement_block':
                for grandchild in reversed(child.children):
                    stack.append((grandchild, current_classes, in_body_status))
                return
        for child in reversed(func_node.children):
            if child.type not in ('formal_parameters', 'async', 'function', 'identifier'):
                stack.append((child, current_classes, in_body_status))

    # ------------------------------------------------------------------
    # 测试文件路径
    # ------------------------------------------------------------------
    def _find_test_file(self, file_path, func_name):
        rel = os.path.relpath(file_path, self.project_root)
        rel_no_ext = os.path.splitext(rel)[0]
        parts = rel_no_ext.split(os.sep)

        if parts and parts[0] == 'src':
            parts[0] = 'test'
        else:
            parts = ['test'] + parts

        return '/'.join(parts) + f'/{func_name}.test.js'

    # ------------------------------------------------------------------
    # 过滤规则
    # ------------------------------------------------------------------
    def _should_filter_method(self, method_info: Dict[str, Any]) -> Tuple[bool, str]:
        reasons = []
        if method_info.get('loc', 0) < self.min_loc_threshold:
            reasons.append(f"loc<{self.min_loc_threshold}")
        if method_info.get('complexity', 0) < self.min_complexity_threshold:
            reasons.append(f"complexity<{self.min_complexity_threshold}")
        if method_info.get('outgoing_degree', 0) < self.min_outgoing_degree_threshold:
            reasons.append(f"outgoing_degree<{self.min_outgoing_degree_threshold}")
        return bool(reasons), ','.join(reasons)

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def extract_and_select_functions(self) -> List[Dict[str, Any]]:
        print(f"开始提取项目函数，文件数量: {len(self.files)}")
        all_functions = self._extract_project_functions()
        all_selected_methods = []

        for method in all_functions:
            file_name = os.path.basename(method.get('src_file', ''))
            self.stats[file_name]['total'] += 1
            should_filter, _ = self._should_filter_method(method)
            if should_filter:
                self.stats[file_name]['filtered'] += 1
            else:
                self.stats[file_name]['candidates'] += 1
                all_selected_methods.append(self._output_method(method))

        print(f"提取函数数: {len(all_functions)}")
        print(f"通过全部阈值: {len(all_selected_methods)}")

        if len(all_selected_methods) < self.min_project_functions:
            print(
                "项目未达到纳入门槛: "
                f"{len(all_selected_methods)} < {self.min_project_functions}，"
                "输出空数据集。"
            )
            all_selected_methods = []

        if self.output_file:
            self._save_to_json(all_selected_methods)

        self._print_statistics_report()
        return all_selected_methods

    def _output_method(self, func: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            'project_root': self.project_root,
            'name': func.get('name', ''),
            'export_kind': func.get('export_kind'),
            'exported_name': func.get('exported_name'),
            'src_file': func.get('src_file', ''),
            'test_file': func.get('test_file', ''),
            'code': func.get('code', ''),
            'is_async': func.get('is_async', False),
            'is_exported': func.get('is_exported', False),
            'type': func.get('type', 'function'),
            'loc': func.get('loc', 0),
            'complexity': func.get('complexity', 0),
            'outgoing_degree': func.get('outgoing_degree', 0),
            'start_line': func.get('start_line'),
            'end_line': func.get('end_line'),
            'imports': func.get('imports') or [],
        }
        if func.get("member_name") is not None:
            result["member_name"] = func["member_name"]
        for key in ('class_name', 'full_class_name', 'class_hierarchy',
                    'class_constructor', 'class_fields', 'class_is_anonymous', 'class_export_kind', 'class_exported_name'):
            if key in func:
                result[key] = func[key]
        return result

    # ------------------------------------------------------------------
    # 输出 / 统计
    # ------------------------------------------------------------------
    def _print_statistics_report(self):
        print("\n" + "=" * 60)
        print("统计报告")
        print("=" * 60)

        total_methods = sum(self.stats[file]['total'] for file in self.stats)
        total_candidates = sum(self.stats[file]['candidates'] for file in self.stats)
        total_filtered = sum(self.stats[file]['filtered'] for file in self.stats)
        total_selected = total_candidates

        print(f"总方法数: {total_methods}")
        print(f"候选方法数: {total_candidates}")
        print(f"过滤方法数: {total_filtered}")
        print(f"最终输出方法数: {total_selected}")
        print(f"涉及文件数: {len(self.stats)}")
        print(
            "Lizard 指标来源: "
            f"完整文件匹配={self.metric_stats['lizard_file_match']}, "
            f"包装片段={self.metric_stats['lizard_wrapped_fragment']}, "
            f"无法测量并排除={self.metric_stats['lizard_unmeasured']}"
        )
        print(
            "筛选条件："
            f"LOC >= {self.min_loc_threshold}, "
            f"CC >= {self.min_complexity_threshold}, "
            f"outgoing degree >= {self.min_outgoing_degree_threshold}"
        )
        print(f"导出限制: {'仅导出函数' if self.only_exported else '包含未导出函数'}")

        for file, stats in self.stats.items():
            if stats.get('total', 0) > 0:
                print(f"\n{file}:")
                print(f"  总方法: {stats.get('total', 0)}")
                print(f"  候选方法: {stats.get('candidates', 0)}")
                print(f"  过滤方法: {stats.get('filtered', 0)}")

    def _save_to_json(self, data: List[Dict[str, Any]]):
        if not self.output_file:
            return
        try:
            with open(self.output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"\n结果已保存到: {self.output_file}")
        except Exception as e:
            print(f"保存JSON文件时出错: {e}")

    def save_to_json(self, output_file: str = None):
        if output_file:
            self.output_file = output_file
        return self.extract_and_select_functions()

    def print_detailed_selection_report(self):
        """兼容旧调用；当前流程不再进行分层选择。"""
        return None


def main():
    parser = argparse.ArgumentParser(
        description="从 JavaScript 项目收集生产源码，并保留达到三个复杂度阈值的公有函数。"
    )
    parser.add_argument('--project-root', required=True, help='JavaScript 项目根目录')
    parser.add_argument('--output', default='selected_functions.json', help='输出 JSON 路径')
    parser.add_argument('--min-loc', type=int, default=50, help='最小非空代码行数，默认 50')
    parser.add_argument('--min-complexity', type=int, default=10, help='最小圈复杂度，默认 10')
    parser.add_argument('--min-outgoing-degree', type=int, default=5, help='最小调用出度，默认 5')
    parser.add_argument(
        '--min-project-functions', type=int, default=5,
        help='项目至少需要保留的合格函数数，默认 5；不足时输出空数据集'
    )
    export_group = parser.add_mutually_exclusive_group()
    export_group.add_argument(
        '--only-exported', dest='only_exported', action='store_true',
        help='只提取可从模块外部访问的函数/类方法（默认）'
    )
    export_group.add_argument(
        '--include-internal', dest='only_exported', action='store_false',
        help='额外提取未导出的内部函数；仅用于分析，不保证可直接生成单元测试'
    )
    parser.set_defaults(only_exported=True)
    args = parser.parse_args()

    project_root = str(Path(args.project_root).resolve())
    javascript_files = discover_javascript_files(project_root)
    print(f'项目根目录: {project_root}')
    print(f'发现生产 JavaScript 文件: {len(javascript_files)}（已排除测试文件/目录及常见构建目录）')

    extractor = JSProjectTestScopeExtractor(
        project_root=project_root,
        file_list=javascript_files,
        output_file=args.output,
        min_loc_threshold=args.min_loc,
        min_complexity_threshold=args.min_complexity,
        min_outgoing_degree_threshold=args.min_outgoing_degree,
        only_exported=args.only_exported,
        min_project_functions=args.min_project_functions,
    )
    selected = extractor.extract_and_select_functions()
    print(f'\n总共保留 {len(selected)} 个函数。')


if __name__ == '__main__':
    main()
