import argparse
import json
import os
import re
from pathlib import Path
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple
from multi_parser import python_parser

try:
    import lizard
except ImportError:  # pragma: no cover - fallback is used only without lizard
    lizard = None


IGNORED_DIRS = {
    'test', 'tests', '__tests__', '__pycache__', '.git', '.svn', '.hg',
    'venv', 'env', '.env', 'virtualenv', 'envs',
    '.vscode', '.idea', '.pytest_cache', '.mypy_cache',
    'build', 'dist', '*.egg-info', 'node_modules',
    'target', 'doc', 'docs', 'example', 'examples', 'coverage',
    'script', 'scripts', 'benchmarks', 'benchmark', '.cargo',
    '.direnv', 'demos',
}

TEST_FILE_PATTERNS = [
    re.compile(r'^test_.*\.py$', re.IGNORECASE),
    re.compile(r'.*_test\.py$', re.IGNORECASE),
    re.compile(r'^conftest\.py$', re.IGNORECASE),
]


def discover_python_files(project_root: str) -> List[str]:
    """递归收集生产 Python 文件，排除测试文件及常见非生产目录。"""
    root_path = Path(project_root).resolve()
    python_files: List[str] = []
    for current_root, dirs, files in os.walk(root_path):
        dirs[:] = [
            d for d in dirs
            if d.lower() not in IGNORED_DIRS
            and not d.lower().endswith('.egg-info')
            and not d.startswith('.')
        ]
        for filename in files:
            if not filename.endswith('.py'):
                continue
            if any(pattern.match(filename) for pattern in TEST_FILE_PATTERNS):
                continue
            full_path = Path(current_root) / filename
            relative_parts = {part.lower() for part in full_path.relative_to(root_path).parts[:-1]}
            if relative_parts.intersection(IGNORED_DIRS):
                continue
            python_files.append(str(full_path))
    return sorted(set(python_files))


class EnhancedPythonFocalExtractor:
    """
    提取生产 Python 文件中的公有函数，并按固定阈值筛选。
    """

    def __init__(self, project_root, file_list, output_file=None,
                 min_loc_threshold=50, min_complexity_threshold=10,
                 min_outgoing_degree_threshold=5, random_seed=42):
        self.project_root = str(Path(project_root).resolve())
        self.files = file_list
        self.output_file = output_file
        self.min_loc_threshold = min_loc_threshold
        self.min_complexity_threshold = min_complexity_threshold
        self.min_outgoing_degree_threshold = min_outgoing_degree_threshold
        self.random_seed = random_seed

        self.stats = defaultdict(lambda: defaultdict(int))

    def extract_and_select_functions(self):
        all_selected_methods = []

        for file_path in self.files:
            try:
                print(f"\n处理文件: {os.path.basename(file_path)}")

                all_methods = self._extract_focal_method(file_path)
                if not all_methods:
                    print(f"    文件中没有提取到方法")
                    continue

                # _extract_focal_method 里已经过滤过 _ 开头，这里保留是为了双保险
                public_methods = [
                    method for method in all_methods
                    if not method.get('name', '').startswith('_')
                ]

                for method in public_methods:
                    should_filter, _ = self._should_filter_method(method)
                    if should_filter:
                        self.stats[os.path.basename(file_path)]['filtered'] += 1
                    else:
                        all_selected_methods.append(self._output_method(method))
                        self.stats[os.path.basename(file_path)]['candidates'] += 1
                print(f"   保留函数: {self.stats[os.path.basename(file_path)]['candidates']} 个")

                self.stats[os.path.basename(file_path)]['total'] = len(all_methods)
                self.stats[os.path.basename(file_path)]['public'] = len(public_methods)

            except SyntaxError as e:
                print(f"语法错误，跳过文件 {file_path}: {e}")
                continue
            except UnicodeDecodeError as e:
                print(f"编码错误，跳过文件 {file_path}: {e}")
                continue
            except Exception as e:
                print(f"处理 {file_path} 时出错: {e}")
                continue

        self._save_to_json(all_selected_methods)
        self._print_statistics_report()
        return all_selected_methods

    def _should_filter_method(self, method_info):
        reasons = []
        if method_info.get('loc', 0) < self.min_loc_threshold:
            reasons.append(f"loc<{self.min_loc_threshold}")
        if method_info.get('complexity', 0) < self.min_complexity_threshold:
            reasons.append(f"complexity<{self.min_complexity_threshold}")
        if method_info.get('outgoing_degree', 0) < self.min_outgoing_degree_threshold:
            reasons.append(f"outgoing_degree<{self.min_outgoing_degree_threshold}")
        return bool(reasons), ','.join(reasons)

    @staticmethod
    def _has_private_enclosing_class(current_classes):
        """Apply Python's underscore-private convention to every owner class."""
        return any(
            str(cls.get('name', '')).startswith('_')
            for cls in current_classes
        )

    def _output_method(self, method):
        """保留与原 JSON 兼容的字段，并附带调用出度。"""
        fields = {
            'project_root': self.project_root, 'name': method.get('name', ''),
            'src_file': method.get('src_file', ''), 'test_file': method.get('test_file', ''),
            'code': method.get('code', ''), 'is_async': method.get('is_async', False),
            'type': method.get('type', 'function'), 'loc': method.get('loc', 0),
            'complexity': method.get('complexity', 0), 'outgoing_degree': method.get('outgoing_degree', 0),
            'param_count': method.get('param_count', 0), 'start_line': method.get('start_line'),
            'end_line': method.get('end_line'), 'imports': method.get('imports') or [],
        }
        for key in ('class_name', 'full_class_name', 'class_constructor', 'class_fields',
                    'class_variables', 'class_hierarchy'):
            if key in method:
                fields[key] = method[key]
        return fields

    # ------------------------------------------------------------------
    # 提取
    # ------------------------------------------------------------------
    def _extract_focal_method(self, file_path):
        """提取文件中所有公有函数，包括参数计数"""
        with open(file_path, 'r', encoding='utf-8') as f:
            code = f.read()
            tree = python_parser.parse(bytes(code, 'utf-8'))
            root_node = tree.root_node

            imports = self._extract_imports(root_node, code)
            class_info_dict = self._extract_all_classes(root_node, code)

            focal_methods = []
            stack = [(root_node, [])]  # (节点, 路径上的类)

            while stack:
                node, current_classes = stack.pop()

                # ★ 修复：单独记录"用于取 code 的节点"，装饰器不会被丢掉
                code_node = node

                # 处理装饰器定义
                if node.type == 'decorated_definition':
                    inner_def = None
                    for child in node.children:
                        if child.type in ('function_definition', 'class_definition'):
                            inner_def = child
                            break

                    if inner_def and inner_def.type == 'function_definition':
                        if self._decorated_definition_has_deprecated(node, code):
                            continue
                        code_node = node       # 外层：含 @decorator
                        node = inner_def       # 内层：function_definition

                # 处理类定义
                if node.type == 'class_definition':
                    class_name = self._get_name(node)
                    if class_name:
                        new_classes = current_classes + [{
                            'name': class_name,
                            'node': node
                        }]
                        for child in reversed(node.children):
                            stack.append((child, new_classes))
                        continue

                # 处理函数定义
                if node.type == 'function_definition':
                    function_name = self._get_name(node)

                    # A public-looking method of ``class _Internal`` is still
                    # an internal API by Python convention.  Reject it just as
                    # we reject underscore-prefixed methods, including when the
                    # private class is an outer class of a nested type.
                    if (function_name and not function_name.startswith('_')
                            and not self._has_private_enclosing_class(current_classes)):
                        parameters = node.child_by_field_name('parameters')
                        # ★ 修复：用 code_node 拿代码，保留装饰器
                        method_code = code_node.text.decode('utf-8')

                        complexity, loc, param_count = self._compute_complexity_and_loc(method_code)
                        outgoing_degree = self._compute_outgoing_degree(node)

                        # ★ 修复：os.path.relpath 替代脆弱的 split
                        try:
                            src_file = os.path.relpath(file_path, str(self.project_root))
                        except ValueError:
                            src_file = str(file_path)

                        method_info = {
                            'project_root': self.project_root,
                            'name': function_name,
                            'src_file': src_file,
                            'test_file': self._gen_test_file_path(file_path, function_name),
                            'code': method_code,
                            'is_async': self._is_async_function(node),
                            'imports': imports,
                            'loc': loc,
                            'complexity': complexity,
                            'outgoing_degree': outgoing_degree,
                            'param_count': param_count,
                            'has_variadic_params': any(n.type in {'list_splat', 'dictionary_splat'}
                                                       for n in self._walk(parameters)) if parameters else False,
                            # ★ 新增：1-based 行号，闭区间
                            'start_line': self._line_of(code_node.start_point),
                            'end_line': self._line_of(code_node.end_point),
                        }

                        if current_classes:
                            class_hierarchy = [cls['name'] for cls in current_classes]
                            full_class_name = '.'.join(class_hierarchy)

                            method_info['type'] = 'method'
                            method_info['class_name'] = current_classes[-1]['name']
                            method_info['full_class_name'] = full_class_name
                            method_info['class_hierarchy'] = class_hierarchy
                            method_info['class_constructor'] = []      
                            method_info['class_fields'] = []
                            method_info['class_variables'] = []

                            class_info = class_info_dict.get(full_class_name)
                            if class_info:
                                if class_info.get('constructor'):
                                    method_info['class_constructor'] = [class_info['constructor']]
                                if class_info.get('fields'):
                                    method_info['class_fields'] = class_info['fields']
                                if class_info.get('class_variables'):
                                    method_info['class_variables'] = class_info['class_variables']
                        else:
                            method_info['type'] = 'function'

                        focal_methods.append(method_info)

                    continue  # 不再遍历函数体内的嵌套函数

                for child in reversed(node.children):
                    stack.append((child, current_classes))

            return focal_methods

    def _walk(self, node):
        stack = [node]
        while stack:
            current = stack.pop()
            yield current
            stack.extend(current.children)

    @staticmethod
    def _line_of(point):
        """兼容 Point 对象与 (row, col) 元组，返回 1-based 行号。"""
        row = point.row if hasattr(point, 'row') else point[0]
        return row + 1

    def _compute_complexity_and_loc(self, code):
        complexity = 1
        loc = len([line for line in code.splitlines() if line.strip()])
        param_count = 0
        try:
            if lizard is None:
                raise ImportError('lizard 未安装')
            report = lizard.analyze_file.analyze_source_code("temp.py", code)
            if report.function_list:
                function = report.function_list[0]
                complexity = int(getattr(function, 'cyclomatic_complexity', complexity))
                loc = int(getattr(function, 'nloc', loc))
                param_count = len(getattr(function, 'full_parameters', []) or [])
        except Exception as e:
            if lizard is not None:
                print(f"[warn] lizard 分析失败，使用近似值: {type(e).__name__}: {e}")
            branches = len(re.findall(r'\b(if|for|while|except|case)\b|\band\b|\bor\b', code))
            complexity = 1 + branches
            signature = code.splitlines()[0] if code.splitlines() else ''
            params_match = re.search(r'\((.*?)\)', signature)
            param_text = params_match.group(1).strip() if params_match else ''
            param_count = len([p for p in param_text.split(',') if p.strip()]) if param_text else 0
        return complexity, loc, param_count

    def _compute_outgoing_degree(self, function_node) -> int:
        """统计函数体内不重复的调用表达式数量，不解析嵌套函数。"""
        callees: Set[str] = set()
        nested_scopes = {'function_definition', 'class_definition', 'lambda'}

        def visit(node, is_root=False):
            if not is_root and node.type in nested_scopes:
                return
            if node.type == 'call':
                function = node.child_by_field_name('function')
                if function is not None:
                    callees.add(function.text.decode('utf-8', errors='replace').strip())
            for child in node.children:
                visit(child)

        visit(function_node, is_root=True)
        return len(callees)

    # ★ 修复：用 os.path 处理路径，避免 split 出 IndexError
    def _gen_test_file_path(self, file_path, function_name):
        try:
            rel = os.path.relpath(file_path, str(self.project_root))
        except ValueError:
            rel = str(file_path)

        temp_path2 = rel.split(".py")[0]
        file_name = os.path.basename(temp_path2)
        temp_dir = os.path.dirname(temp_path2)

        test_path = os.path.join(
            temp_dir, "Test" + file_name, "test_" + function_name + ".py"
        ).replace(os.sep, '/')

        if "src/" in test_path:
            return test_path.replace('src/', 'test/')
        return "tests/" + test_path

    # ★ 修复：imports 拍平成 list，与 Java 版保持一致
    def _extract_imports(self, root_node, code):
        imports = []

        def traverse_imports(node):
            if node.type in ('import_statement', 'import_from_statement'):
                text = node.text.decode('utf-8').strip()
                imports.append(text)
            for child in node.children:
                traverse_imports(child)

        traverse_imports(root_node)
        return list(dict.fromkeys(imports))   # 去重并保持出现顺序

    def extract_file_imports(self, file_path):
        """提取文件中全部 import 语句（供筛选输出/测试生成复用）"""
        with open(file_path, 'r', encoding='utf-8') as f:
            code = f.read()
        tree = python_parser.parse(bytes(code, 'utf-8'))
        return self._extract_imports(tree.root_node, code)

    # ★ 修复：嵌套类的 full_name 正确传递父类链
    def _extract_all_classes(self, root_node, code):
        class_info_dict = {}

        def extract_class_details(class_node, parent_classes):
            class_name = self._get_name(class_node)
            if not class_name:
                return None

            full_class_name = '.'.join(parent_classes + [class_name])

            class_info = {
                'name': class_name,
                'full_name': full_class_name,
                'constructor': None,
                'fields': [],
                'class_variables': [],
                'nested_classes': []
            }

            class_body = None
            for child in class_node.children:
                if child.type == 'block':
                    class_body = child
                    break

            if class_body:
                for child in class_body.children:
                    if child.type == 'decorated_definition':
                        inner = None
                        for gc in child.children:
                            if gc.type == 'function_definition':
                                inner = gc
                                break
                        if inner:
                            func_name = self._get_name(inner)
                            if func_name == '__init__':
                                if not self._decorated_definition_has_deprecated(child, code):
                                    class_info['constructor'] = inner.text.decode('utf-8')
                        continue

                    if child.type == 'function_definition':
                        func_name = self._get_name(child)
                        if func_name == '__init__':
                            class_info['constructor'] = child.text.decode('utf-8')

                    elif child.type == 'expression_statement':
                        assignment = self._find_assignment(child)
                        if assignment:
                            if not self._is_instance_assignment(assignment, code):
                                var_info = self._extract_variable_info(assignment, code)
                                if var_info:
                                    class_info['class_variables'].append(var_info)

                    elif child.type == 'assignment':
                        if self._is_instance_assignment(child, code):
                            field_info = self._extract_field_info(child, code)
                            if field_info:
                                class_info['fields'].append(field_info)

            return class_info

        def traverse(node, parent_classes):
            if node.type == 'class_definition':
                info = extract_class_details(node, parent_classes)
                if info:
                    class_info_dict[info['full_name']] = info
                    new_parents = parent_classes + [info['name']]
                    for child in node.children:
                        traverse(child, new_parents)
                    return
            for child in node.children:
                traverse(child, parent_classes)

        traverse(root_node, [])
        return class_info_dict

    def _get_name(self, node):
        for child in node.children:
            if child.type == 'identifier':
                return child.text.decode('utf-8')
        return None

    def _is_async_function(self, function_node):
        for child in function_node.children:
            if child.type == 'async':
                return True
        return False

    def _decorated_definition_has_deprecated(self, decorated_node, code):
        try:
            for child in decorated_node.children:
                text = child.text.decode('utf-8').strip()
                if text.startswith('@'):
                    if re.search(r'\bdeprecated\b', text.lower()):
                        return True
            return False
        except Exception:
            return False

    def _find_assignment(self, node):
        stack = [node]
        while stack:
            current = stack.pop()
            if current.type == 'assignment':
                return current
            for child in current.children:
                stack.append(child)
        return None

    def _is_instance_assignment(self, assignment_node, code):
        for child in assignment_node.children:
            if child.type == 'attribute':
                attr_text = child.text.decode('utf-8')
                if attr_text.startswith('self.'):
                    return True
        return False

    def _extract_variable_info(self, assignment_node, code):
        try:
            left_side = None
            left_node = None

            for child in assignment_node.children:
                if child.type in ('identifier', 'attribute'):
                    left_side = child.text.decode('utf-8')
                    left_node = child
                elif child.type == '=':
                    break   # ★ 修复：不再尝试取 right_side（从未使用）

            if left_side:
                if isinstance(left_side, bytes):
                    left_side_str = left_side.decode('utf-8')
                else:
                    left_side_str = str(left_side)

                if left_side_str.startswith('_'):
                    return None

                if left_node and left_node.type == 'attribute':
                    attr_parts = left_side_str.split('.')
                    if attr_parts and attr_parts[-1].startswith('_'):
                        return None

                return assignment_node.text.decode('utf-8')
        except Exception:
            pass
        return None

    def _extract_field_info(self, assignment_node, code):
        return self._extract_variable_info(assignment_node, code)

    def _save_to_json(self, methods):
        if not self.output_file:
            return
        serializable_methods = []
        for method in methods:
            serializable_method = method.copy()
            for key, value in serializable_method.items():
                if isinstance(value, bytes):
                    serializable_method[key] = value.decode('utf-8')
            serializable_methods.append(serializable_method)

        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(serializable_methods, f, indent=2, ensure_ascii=False)

    def _print_statistics_report(self):
        print("\n" + "=" * 80)
        print("Python 函数筛选统计报告")
        print("=" * 80)

        total_files = len(self.stats)
        total_methods = sum(stats.get('total', 0) for stats in self.stats.values())
        total_public = sum(stats.get('public', 0) for stats in self.stats.values())
        total_candidates = sum(stats.get('candidates', 0) for stats in self.stats.values())
        total_filtered = sum(stats.get('filtered', 0) for stats in self.stats.values())
        total_selected = total_candidates

        print(f"\n 总体统计:")
        print(f"  处理文件数: {total_files}")
        print(f"  提取方法总数: {total_methods}")
        print(f"  公有方法数: {total_public}")
        print(f"  通过全部阈值的方法数: {total_candidates}")
        print(f"  过滤方法数: {total_filtered}")
        print(f"  最终输出方法数: {total_selected}")

        if total_candidates > 0:
            filter_rate = total_filtered / total_public * 100 if total_public > 0 else 0
            selection_rate = total_selected / total_files * 100 if total_files > 0 else 0
            print(f"  过滤率: {filter_rate:.1f}%")
            print(f"  选择率: {selection_rate:.1f}%")

        print(
            "  筛选条件："
            f"LOC >= {self.min_loc_threshold}, "
            f"CC >= {self.min_complexity_threshold}, "
            f"outgoing degree >= {self.min_outgoing_degree_threshold}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="从 Python 项目收集生产源码，并保留达到三个复杂度阈值的公有函数。"
    )
    parser.add_argument('--project-root', required=True, help='Python 项目根目录')
    parser.add_argument('--output', default='selected_functions.json', help='输出 JSON 路径')
    parser.add_argument('--min-loc', type=int, default=50, help='最小非空代码行数，默认 50')
    parser.add_argument('--min-complexity', type=int, default=10, help='最小圈复杂度，默认 10')
    parser.add_argument('--min-outgoing-degree', type=int, default=5, help='最小调用出度，默认 5')
    args = parser.parse_args()

    project_root = str(Path(args.project_root).resolve())
    python_files = discover_python_files(project_root)
    print(f'项目根目录: {project_root}')
    print(f'发现生产 Python 文件: {len(python_files)}（已排除测试文件/目录及常见构建目录）')

    extractor = EnhancedPythonFocalExtractor(
        project_root=project_root,
        file_list=python_files,
        output_file=args.output,
        min_loc_threshold=args.min_loc,
        min_complexity_threshold=args.min_complexity,
        min_outgoing_degree_threshold=args.min_outgoing_degree,
    )
    selected = extractor.extract_and_select_functions()
    print(f'\n总共保留 {len(selected)} 个函数。')


if __name__ == '__main__':
    main()
