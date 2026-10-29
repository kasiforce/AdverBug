import os
import json
import re
import ast
import radon
import numpy as np
import random
# from radon.complexity import cc_visit
# from radon.raw import analyze
from collections import defaultdict
from multi_parser import python_parser
from file_select import *


# class StratifiedFunctionSelector:
#     """
#     分层函数选择器：对文件内候选函数进行评分、分层和抽样
#     """

#     def __init__(self, random_seed=42):
#         """
#         初始化选择器

#         Args:
#             random_seed: 固定随机种子，确保结果可重复
#         """
#         self.random_seed = random_seed
#         random.seed(random_seed)
#         np.random.seed(random_seed)

#     def select_functions_from_file(self, file_path, candidate_functions):
#         """
#         从单个文件的候选函数中进行分层抽样

#         Args:
#             file_path: 文件路径
#             candidate_functions: 候选函数列表

#         Returns:
#             dict: 抽样结果
#         """
#         if not candidate_functions:
#             return {
#                 'file_path': file_path,
#                 'file_name': os.path.basename(file_path),
#                 'total_candidates': 0,
#                 'selected_functions': [],
#                 'stratification': {}
#             }

#         # 步骤1: 为每个函数计算FuncScore
#         scored_functions = self._calculate_function_scores(candidate_functions)

#         # 步骤2: 按FuncScore排序
#         scored_functions.sort(key=lambda x: x['func_score'])

#         # 步骤3: 分位数分层 (33%分位)
#         n_functions = len(scored_functions)
#         simple_cut = int(np.ceil(n_functions * 0.67))  # 前67%为Simple
#         medium_cut = int(np.ceil(n_functions * 0.33))  # 前33%为Complex

#         # 分成三层
#         simple_tier = scored_functions[:simple_cut] if simple_cut > 0 else []
#         medium_tier = scored_functions[simple_cut:medium_cut] if medium_cut > simple_cut else []
#         complex_tier = scored_functions[medium_cut:] if medium_cut < n_functions else []

#         # 步骤4: 分层抽样
#         selected_functions = self._sample_from_tiers(simple_tier, medium_tier, complex_tier)

#         return {
#             'file_path': file_path,
#             'file_name': os.path.basename(file_path),
#             'total_candidates': n_functions,
#             'selected_functions': selected_functions,
#             'stratification': {
#                 'Simple': {
#                     'count': len(simple_tier),
#                     'score_range': (simple_tier[0]['func_score'] if simple_tier else 0,
#                                    simple_tier[-1]['func_score'] if simple_tier else 0)
#                 },
#                 'Medium': {
#                     'count': len(medium_tier),
#                     'score_range': (medium_tier[0]['func_score'] if medium_tier else 0,
#                                    medium_tier[-1]['func_score'] if medium_tier else 0)
#                 },
#                 'Complex': {
#                     'count': len(complex_tier),
#                     'score_range': (complex_tier[0]['func_score'] if complex_tier else 0,
#                                    complex_tier[-1]['func_score'] if complex_tier else 0)
#                 }
#             }
#         }

#     def _calculate_function_scores(self, functions):
#         """
#         计算每个函数的FuncScore

#         FuncScore(f) = a·CC(f) + b·branch_count(f) + c·param_count(f)
#         先标准化，再等权
#         """
#         if not functions:
#             return []

#         # 提取三个指标
#         complexities = []
#         branch_counts = []
#         param_counts = []

#         for func in functions:
#             # 获取圈复杂度
#             cc = func.get('complexity', 1)
#             complexities.append(cc)

#             # 分支数 = 圈复杂度 - 1
#             branch_count = max(0, cc - 1)
#             branch_counts.append(branch_count)

#             # 获取参数个数
#             param_count = func.get('param_count', 0)
#             param_counts.append(param_count)

#         # Z-Score标准化
#         complexities_norm = self._z_score_normalize(complexities)
#         branch_counts_norm = self._z_score_normalize(branch_counts)
#         param_counts_norm = self._z_score_normalize(param_counts)

#         # 计算标准化后的FuncScore (等权)
#         scored_functions = []
#         for i, func in enumerate(functions):
#             func_score = (
#                 complexities_norm[i] +
#                 branch_counts_norm[i] +
#                 param_counts_norm[i]
#             ) / 3.0

#             scored_func = func.copy()
#             scored_func['func_score'] = round(func_score, 4)
#             scored_func['raw_metrics'] = {
#                 'complexity': complexities[i],
#                 'branch_count': branch_counts[i],
#                 'param_count': param_counts[i]
#             }
#             scored_functions.append(scored_func)

#         return scored_functions

#     def _z_score_normalize(self, values):
#         """Z-Score标准化"""
#         if not values:
#             return []

#         arr = np.array(values)
#         mean = np.mean(arr)
#         std = np.std(arr)

#         if std == 0:
#             return np.zeros_like(arr).tolist()

#         return ((arr - mean) / std).tolist()

#     def _sample_from_tiers(self, simple_tier, medium_tier, complex_tier):
#         """
#         从各层抽样：
#         - Simple: 1个
#         - Medium: 1-2个
#         - Complex: 1个
#         """
#         selected = []

#         # Simple层: 抽1个
#         if simple_tier:
#             if len(simple_tier) >= 1:
#                 selected.append(random.choice(simple_tier))
#             else:
#                 selected.extend(simple_tier)

#         # Medium层: 抽1-2个
#         if medium_tier:
#             k = min(2, len(medium_tier))
#             if k >= 1:
#                 selected.extend(random.sample(medium_tier, k) if len(medium_tier) >= k else medium_tier)
#             else:
#                 selected.extend(medium_tier)

#         # Complex层: 抽1个
#         if complex_tier:
#             if len(complex_tier) >= 1:
#                 selected.append(random.choice(complex_tier))
#             else:
#                 selected.extend(complex_tier)

#         return selected

#     def print_selection_report(self, selection_result):
#         """打印选择结果报告"""
#         if not selection_result['selected_functions']:
#             print(f"文件 {selection_result['file_name']}: 没有选择任何函数")
#             return

#         print("=" * 80)
#         print(f"函数选择报告: {selection_result['file_name']}")
#         print("=" * 80)

#         print(f"\n 文件信息:")
#         print(f"  文件路径: {selection_result['file_path']}")
#         print(f"  候选函数总数: {selection_result['total_candidates']}")
#         print(f"  选择函数数: {len(selection_result['selected_functions'])}")

#         print(f"\n 分层统计:")
#         for tier_name, tier_info in selection_result['stratification'].items():
#             print(f"  {tier_name}层:")
#             print(f"    函数数量: {tier_info['count']}")
#             print(f"    得分范围: {tier_info['score_range'][0]:.4f} - {tier_info['score_range'][1]:.4f}")

#         print(f"\n 选择的函数:")
#         for i, func in enumerate(selection_result['selected_functions'], 1):
#             print(f"  {i}. {func.get('full_class_name', '')}.{func.get('name', '')}")
#             print(f"     层: {self._get_tier_for_func(func, selection_result)}")
#             print(f"     得分: {func.get('func_score', 0):.4f}")
#             print(f"     圈复杂度: {func.get('raw_metrics', {}).get('complexity', 0)}")
#             print(f"     参数个数: {func.get('raw_metrics', {}).get('param_count', 0)}")
#             print(f"     代码行数: {func.get('loc', 'N/A')}")

#     def _get_tier_for_func(self, func, selection_result):
#         """确定函数属于哪一层"""
#         func_score = func.get('func_score', 0)

#         for tier_name, tier_info in selection_result['stratification'].items():
#             min_score, max_score = tier_info['score_range']
#             if min_score <= func_score <= max_score:
#                 return tier_name

#         return "Unknown"


class StratifiedFunctionSelector:
    """
    分层函数选择器：对文件内候选函数进行评分、分层和抽样
    """

    def __init__(self, random_seed=42):
        """
        初始化选择器

        Args:
            random_seed: 固定随机种子，确保结果可重复
        """
        self.random_seed = random_seed
        random.seed(random_seed)
        np.random.seed(random_seed)

    def select_functions_from_file(self, file_path, candidate_functions):
        """
        从单个文件的候选函数中进行分层抽样

        Args:
            file_path: 文件路径
            candidate_functions: 候选函数列表

        Returns:
            dict: 抽样结果
        """
        if not candidate_functions:
            return {
                'file_path': file_path,
                'file_name': os.path.basename(file_path),
                'total_candidates': 0,
                'selected_functions': [],
                'stratification': {}
            }

        # 步骤1: 为每个函数计算FuncScore
        scored_functions = self._calculate_function_scores(candidate_functions)

        # 步骤2: 按FuncScore排序
        scored_functions.sort(key=lambda x: x['func_score'])

        # 步骤3: 分位数分层 (33%分位)
        n_functions = len(scored_functions)

        simple_cut = int(np.ceil(n_functions * 0.33))  # 前67%为Simple
        medium_cut = int(np.ceil(n_functions * 0.67))  # 前33%为Complex

        # 分成三层
        simple_tier = scored_functions[:simple_cut] if simple_cut > 0 else []
        medium_tier = scored_functions[simple_cut:medium_cut] if medium_cut > simple_cut else []
        complex_tier = scored_functions[medium_cut:] if medium_cut < n_functions else []

        if not simple_tier and n_functions > 0:
            simple_tier = [scored_functions[-1]]
            if complex_tier and complex_tier[-1] == simple_tier[0]:
                complex_tier = complex_tier[:-1]

        # 步骤4: 分层抽样
        selected_functions = self._sample_from_tiers(simple_tier, medium_tier, complex_tier)

        return {
            'file_path': file_path,
            'file_name': os.path.basename(file_path),
            'total_candidates': n_functions,
            'selected_functions': selected_functions,
            'stratification': {
                'Simple': {
                    'count': len(simple_tier),
                    'score_range': (simple_tier[0]['func_score'] if simple_tier else 0,
                                    simple_tier[-1]['func_score'] if simple_tier else 0),
                    'functions': [f['name'] for f in simple_tier]
                },
                'Medium': {
                    'count': len(medium_tier),
                    'score_range': (medium_tier[0]['func_score'] if medium_tier else 0,
                                    medium_tier[-1]['func_score'] if medium_tier else 0),
                    'functions': [f['name'] for f in medium_tier]
                },
                'Complex': {
                    'count': len(complex_tier),
                    'score_range': (complex_tier[0]['func_score'] if complex_tier else 0,
                                    complex_tier[-1]['func_score'] if complex_tier else 0),
                    'functions': [f['name'] for f in complex_tier]
                }
            }
        }

    def _calculate_function_scores(self, functions):
        """
        计算每个函数的FuncScore

        FuncScore(f) = a·CC(f) + b·branch_count(f) + c·param_count(f)
        先标准化，再等权
        """
        if not functions:
            return []

        # 提取三个指标
        complexities = []
        branch_counts = []
        param_counts = []

        for func in functions:
            # 获取圈复杂度
            cc = func.get('complexity', 1)
            complexities.append(cc)

            # 分支数 = 圈复杂度 - 1
            branch_count = max(0, cc - 1)
            branch_counts.append(branch_count)

            # 获取参数个数
            param_count = func.get('param_count', 0)
            param_counts.append(param_count)

        # Z-Score标准化
        complexities_norm = self._z_score_normalize(complexities)
        branch_counts_norm = self._z_score_normalize(branch_counts)
        param_counts_norm = self._z_score_normalize(param_counts)

        # 计算标准化后的FuncScore (等权)
        scored_functions = []
        for i, func in enumerate(functions):
            func_score = (
                                 complexities_norm[i] +
                                 branch_counts_norm[i] +
                                 param_counts_norm[i]
                         ) / 3.0

            scored_func = func.copy()
            scored_func['func_score'] = round(func_score, 4)
            scored_func['raw_metrics'] = {
                'complexity': complexities[i],
                'branch_count': branch_counts[i],
                'param_count': param_counts[i]
            }
            scored_functions.append(scored_func)

        return scored_functions

    def _z_score_normalize(self, values):
        """Z-Score标准化"""
        if not values:
            return []

        arr = np.array(values)
        mean = np.mean(arr)
        std = np.std(arr)

        if std == 0:
            return np.zeros_like(arr).tolist()

        return ((arr - mean) / std).tolist()

    def _sample_from_tiers(self, simple_tier, medium_tier, complex_tier):
        """
        从各层抽样：
        - Simple: 1个
        - Medium: 1-2个
        - Complex: 1个
        """
        selected = []

        # Simple层: 抽1个
        if simple_tier:
            if len(simple_tier) >= 1:
                selected.append(random.choice(simple_tier))
            else:
                selected.extend(simple_tier)

        # Medium层: 抽1-2个
        if medium_tier:
            k = min(2, len(medium_tier))
            if k >= 1:
                selected.extend(random.sample(medium_tier, k) if len(medium_tier) >= k else medium_tier)
            else:
                selected.extend(medium_tier)

        # Complex层: 抽1个
        if complex_tier:
            if len(complex_tier) >= 1:
                selected.append(random.choice(complex_tier))
            else:
                selected.extend(complex_tier)

        return selected

    def print_selection_report(self, selection_result):
        """打印选择结果报告"""
        if not selection_result['selected_functions']:
            print(f"文件 {selection_result['file_name']}: 没有选择任何函数")
            return

        print("=" * 80)
        print(f"函数选择报告: {selection_result['file_name']}")
        print("=" * 80)

        print(f"\n 文件信息:")
        print(f"  文件路径: {selection_result['file_path']}")
        print(f"  候选函数总数: {selection_result['total_candidates']}")
        print(f"  选择函数数: {len(selection_result['selected_functions'])}")

        print(f"\n 分层统计:")
        for tier_name, tier_info in selection_result['stratification'].items():
            print(f"  {tier_name}层:")
            print(f"    函数数量: {tier_info['count']}")
            print(f"    得分范围: {tier_info['score_range'][0]:.4f} - {tier_info['score_range'][1]:.4f}")
            if tier_info.get('functions'):
                print(f"    函数列表: {', '.join(tier_info['functions'])}")

        print(f"\n 选择的函数:")
        for i, func in enumerate(selection_result['selected_functions'], 1):
            print(f"  {i}. {func.get('full_class_name', '')}.{func.get('name', '')}")
            print(f"     层: {self._get_tier_for_func(func, selection_result)}")
            print(f"     得分: {func.get('func_score', 0):.4f}")
            print(f"     圈复杂度: {func.get('raw_metrics', {}).get('complexity', 0)}")
            print(f"     参数个数: {func.get('raw_metrics', {}).get('param_count', 0)}")
            print(f"     代码行数: {func.get('loc', 'N/A')}")

    def _get_tier_for_func(self, func, selection_result):
        """确定函数属于哪一层"""
        func_score = func.get('func_score', 0)
        func_name = func.get('name', '')

        # 通过函数名和得分在分层信息中查找
        for tier_name, tier_info in selection_result['stratification'].items():
            if func_name in tier_info.get('functions', []):
                return tier_name

        return "Unknown"