import numpy as np
import radon
# from radon.complexity import cc_visit
# from radon.raw import analyze
import lizard
import os
import random
import json
from collections import defaultdict


class FileQualityAnalyzer:
    """
    完整的文件质量分析器，包含：
    1. 计算文件质量得分（标准化等权）
    2. 按模块/包分组进行分位数分层
    3. 在每个层级中随机抽样
    """

    def __init__(self, language, random_seed=42, sampling_k=3):
        """
        初始化分析器

        Args:
            random_seed: 固定随机种子，确保结果可重复
            sampling_k: 每个层级抽样数量K
        """
        self.language = language.lower()
        self.random_seed = random_seed
        self.sampling_k = sampling_k
        random.seed(random_seed)
        np.random.seed(random_seed)

        # 存储所有分析结果
        self.all_results = []
        self.grouped_results = defaultdict(list)
        self.stratification_results = {}

    def analyze_file_raw_metrics(self, file_path):
        """
        分析单个Python文件，仅计算原始指标。

        Args:
            file_path: Python文件路径

        Returns:
            dict: 包含原始指标的字典
        """

        # 使用Radon获取圈复杂度
        # complexity_results = cc_visit(code)
        # raw_metrics = analyze(code)
        report = lizard.analyze_file(file_path)

        # 计算原始指标
        if report:
            avg_CC = 0
            max_CC = 0
            total_branches = 0

            if report.function_list:
                complexities = [block.__dict__['cyclomatic_complexity'] for block in report.function_list]
                total_branches = sum(block.__dict__['cyclomatic_complexity'] - 1 for block in report.function_list)

                avg_CC = sum(complexities) / len(complexities) if len(complexities) > 0 else 0
                max_CC = max(complexities)
            loc = report.__dict__['nloc']
            branch_density = total_branches / loc if loc > 0 else 0
            function_count = len(report.function_list)
        else:
            avg_CC = 0
            max_CC = 0
            branch_density = 0
            function_count = 0
            total_branches = 0

        return {
            'file_info': {
                'file_name': os.path.basename(file_path),
                'file_path': file_path,
                'loc': loc,
                'function_count': function_count,
                'total_branches': total_branches
            },
            'raw_metrics': {
                'avg_CC': avg_CC,
                'max_CC': max_CC,
                'branch_density': branch_density
            }
        }

    def calculate_normalized_scores(self, results):
        """
        对分析结果进行标准化，计算等权得分。

        Args:
            results: 原始指标结果列表

        Returns:
            list: 包含标准化得分的完整结果列表
        """
        if not results:
            return []

        # 提取原始指标用于计算标准化参数
        raw_metrics_list = [r['raw_metrics'] for r in results]

        # 计算Z-Score标准化所需的全局统计量
        avg_cc_list = [m['avg_CC'] for m in raw_metrics_list]
        max_cc_list = [m['max_CC'] for m in raw_metrics_list]
        branch_density_list = [m['branch_density'] for m in raw_metrics_list]

        global_stats = {
            'avg_CC': {'mean': np.mean(avg_cc_list), 'std': np.std(avg_cc_list) if np.std(avg_cc_list) != 0 else 1},
            'max_CC': {'mean': np.mean(max_cc_list), 'std': np.std(max_cc_list) if np.std(max_cc_list) != 0 else 1},
            'branch_density': {'mean': np.mean(branch_density_list),
                               'std': np.std(branch_density_list) if np.std(branch_density_list) != 0 else 1}
        }

        # 对每个结果进行标准化并计算得分
        complete_results = []
        for result in results:
            # 标准化
            norm_avg_cc = self._normalize_value(result['raw_metrics']['avg_CC'], 'avg_CC', global_stats)
            norm_max_cc = self._normalize_value(result['raw_metrics']['max_CC'], 'max_CC', global_stats)
            norm_branch_density = self._normalize_value(result['raw_metrics']['branch_density'], 'branch_density',
                                                        global_stats)

            # 等权得分
            final_score = (norm_avg_cc + norm_max_cc + norm_branch_density) / 3.0

            complete_result = {
                **result,
                'normalized_metrics': {
                    'norm_avg_CC': round(norm_avg_cc, 4),
                    'norm_max_CC': round(norm_max_cc, 4),
                    'norm_branch_density': round(norm_branch_density, 4)
                },
                'score': round(final_score, 4),
                'global_stats': global_stats
            }
            complete_results.append(complete_result)

        return complete_results

    def _normalize_value(self, value, metric_name, global_stats):
        """Z-Score标准化"""
        stats = global_stats[metric_name]
        mean, std = stats['mean'], stats['std']
        return (value - mean) / std if std != 0 else 0.0

    def _should_skip_file(self, filename: str) -> bool:
        """判断是否应该跳过该文件"""
        # 基本忽略规则
        if filename in ['conftest.py', 'setup.py', '__about__.py', '__version__.py']:
            return True

        # 测试文件模式
        if filename.startswith('test_') or filename.endswith('_test.py'):
            return True

        return False

    def _is_in_ignored_path(self, root_path: str, ignore_dirs: set) -> bool:
        parts = root_path.split(os.sep)
        for part in parts:
            if part in ignore_dirs:
                return True
        return False

    def analyze_directory(self, directory_path):
        """
        分析目录下的所有Python文件。

        Args:
            directory_path: 目录路径

        Returns:
            list: 分析结果列表
        """
        print(f"开始分析目录: {directory_path}")

        all_raw_results = []

        # 定义要忽略的目录模式
        IGNORE_DIRS = {
            'test', 'tests', '__tests__', '__pycache__', '.git', '.svn', '.hg',
            'venv', 'env', '.env', 'virtualenv', 'envs',
            '.vscode', '.idea', '.pytest_cache', '.mypy_cache',
            'build', 'dist', '*.egg-info', 'node_modules',
            'target', 'doc', 'docs', 'example', 'examples', 'coverage', 'script', 'scripts', 'benchmarks',
            'benchmark', '.cargo', '.direnv', 'demos'
        }

        for root, dirs, files in os.walk(directory_path):
            # 过滤掉需要忽略的目录（仅按完整目录名）
            dirs[:] = [
                d for d in dirs
                if d not in IGNORE_DIRS
                   and not d.startswith('.')
            ]

            # 若当前根目录本身是需要忽略的目录，直接跳过
            if any(part in IGNORE_DIRS for part in root.split(os.sep)):
                continue

            for file in files:
                # 检查文件路径是否包含忽略目录
                if self._is_in_ignored_path(root, IGNORE_DIRS):
                    continue

                if self.language == "python":
                    # 检查文件扩展名
                    if not file.endswith('.py'):
                        continue

                    # 检查是否为测试文件或应忽略的文件
                    if self._should_skip_file(file):
                        continue

                if self.language == "java":
                    if not file.endswith('.java'):
                        continue

                    if file.endswith(('Test.java', 'Tests.java')) or file.startswith("Test"):
                        continue

                if self.language == "javascript":
                    if not file.endswith('.js'):
                        continue

                    if ".test." in file or ".tests." in file or ".spec." in file or "_spec." in file or "test_" in file or "_test." in file:
                        continue

                if self.language == "rust":
                    if not file.endswith('.rs'):
                        continue

                    if file.endswith(('test.rs', 'tests.rs')) or file.startswith("test"):
                        continue

                file_path = os.path.join(root, file)

                try:
                    # 添加调试信息
                    # print(f"处理文件: {file_path}")

                    result = self.analyze_file_raw_metrics(file_path)
                    if result:
                        all_raw_results.append(result)

                except SyntaxError as e:
                    print(f"语法错误，跳过文件 {file_path}: {e}")
                    continue
                except UnicodeDecodeError as e:
                    print(f"编码错误，跳过文件 {file_path}: {e}")
                    continue
                except Exception as e:
                    print(f"处理 {file_path} 时出错: {e}")
                    continue

        if not all_raw_results:
            print("未找到有效的Python文件进行分析")
            return []

        # 保留原始文件指标，不再计算文件级标准化 score。
        self.all_results = all_raw_results

        print(f"分析完成，共处理 {len(self.all_results)} 个文件")
        return self.all_results

    def group_by_module(self, results=None):
        """
        按模块/包对文件进行分组。

        Args:
            results: 分析结果列表，如果为None则使用self.all_results

        Returns:
            dict: 按模块分组的结果字典
        """
        if results is None:
            results = self.all_results

        grouped = defaultdict(list)

        for result in results:
            file_path = result['file_info']['file_path']

            # 简单按目录结构分组：取文件路径的上一级目录作为模块名
            # 可以根据实际需求调整分组逻辑
            module_name = os.path.basename(os.path.dirname(file_path))
            if module_name == '':
                module_name = 'root'  # 根目录下的文件

            grouped[module_name].append(result)

        self.grouped_results = grouped
        return grouped

    def quantile_stratification(self, group_name=None, group_results=None):
        """
        对指定组内的文件进行分位数分层。

        Args:
            group_name: 组名，如果为None则对所有文件进行处理
            group_results: 组的分析结果列表，如果为None则使用对应组的结果

        Returns:
            dict: 分层结果
        """
        if group_results is None:
            if group_name is None:
                # 处理所有文件
                results = self.all_results
                group_name = 'all'
            else:
                results = self.grouped_results.get(group_name, [])
        else:
            results = group_results

        if not results:
            print(f"警告: 组 '{group_name}' 中没有文件")
            return {}

        # 按得分排序（从高到低：得分越高表示质量越差）
        sorted_results = sorted(results, key=lambda x: x['score'], reverse=True)
        n_files = len(sorted_results)

        # 计算分位数切分点
        low_cut = int(np.ceil(n_files * 0.67))  # bottom 33%
        mid_cut = int(np.ceil(n_files * 0.33))  # middle 33%

        # 分成三层
        low_tier = sorted_results[low_cut:] if low_cut < n_files else []
        mid_tier = sorted_results[mid_cut:low_cut] if mid_cut < low_cut else []
        high_tier = sorted_results[:mid_cut] if mid_cut > 0 else sorted_results

        # 确保每个文件只属于一层（处理边界情况）
        if not low_tier and n_files > 0:
            low_tier = [sorted_results[-1]]
            if high_tier and high_tier[-1] == low_tier[0]:
                high_tier = high_tier[:-1]

        stratification = {
            'group_name': group_name,
            'total_files': n_files,
            'High': {
                'tier_name': 'High (top 33%)',
                'description': '质量最差的33%文件（得分最高）',
                'files': high_tier,
                'count': len(high_tier),
                'score_range': (high_tier[-1]['score'] if high_tier else 0,
                                high_tier[0]['score'] if high_tier else 0)
            },
            'Mid': {
                'tier_name': 'Mid (middle 33%)',
                'description': '质量中等的33%文件',
                'files': mid_tier,
                'count': len(mid_tier),
                'score_range': (mid_tier[-1]['score'] if mid_tier else 0,
                                mid_tier[0]['score'] if mid_tier else 0)
            },
            'Low': {
                'tier_name': 'Low (bottom 33%)',
                'description': '质量最好的33%文件（得分最低）',
                'files': low_tier,
                'count': len(low_tier),
                'score_range': (low_tier[-1]['score'] if low_tier else 0,
                                low_tier[0]['score'] if low_tier else 0)
            }
        }

        # 保存结果
        if group_name not in self.stratification_results:
            self.stratification_results[group_name] = {}
        self.stratification_results[group_name] = stratification

        return stratification

    def stratified_sampling(self, stratification, k=None):
        """
        对分层结果进行随机抽样。

        Args:
            stratification: 分层结果字典
            k: 每个层级的抽样数量，如果为None则使用self.sampling_k

        Returns:
            dict: 抽样结果
        """
        if k is None:
            k = self.sampling_k

        sampling_results = {
            'group_name': stratification['group_name'],
            'total_files': stratification['total_files'],
            'sampling_k': k,
            'random_seed': self.random_seed,
            'tiers': {}
        }

        for tier_name in ['High', 'Mid', 'Low']:
            tier = stratification[tier_name]
            files = tier['files']

            if len(files) <= k:
                # 如果该层文件数少于k，全部选取
                sampled_files = files.copy()
                sampling_type = 'all'
            else:
                # 随机抽取k个文件
                sampled_files = random.sample(files, k)
                sampling_type = 'random'

            # 获取文件基本信息
            sampled_info = []
            for file in sampled_files:
                sampled_info.append({
                    'file_name': file['file_info']['file_name'],
                    'file_path': file['file_info']['file_path'],
                    'score': file['score'],
                    'loc': file['file_info']['loc'],
                    'function_count': file['file_info']['function_count']
                })

            sampling_results['tiers'][tier_name] = {
                'tier_name': tier['tier_name'],
                'total_in_tier': tier['count'],
                'sampled_count': len(sampled_files),
                'sampling_type': sampling_type,
                'sampled_files': sampled_info
            }

        return sampling_results

    def analyze_project(self, project_path, group_by_module=True):
        """
        完整分析项目：计算得分 → 分组 → 分层 → 抽样。

        Args:
            project_path: 项目路径
            group_by_module: 是否按模块分组

        Returns:
            dict: 完整的分析结果
        """
        print("=" * 70)
        print("开始完整项目分析")
        print("=" * 70)

        # 步骤1: 分析目录，计算文件得分
        self.analyze_directory(project_path)

        if not self.all_results:
            print("分析失败：未找到可分析的文件")
            return None

        # 步骤2: 按模块分组（可选）
        if group_by_module:
            self.group_by_module()
            groups = self.grouped_results
            print(f"\n按模块分组完成，共 {len(groups)} 个组:")
            for group_name, files in groups.items():
                print(f"  {group_name}: {len(files)} 个文件")
        else:
            # 将所有文件视为一个组
            groups = {'all': self.all_results}
            self.grouped_results = groups

        # 直接返回全部文件路径，不再进行 score 分层或抽样。
        return [result['file_info']['file_path'] for result in self.all_results]

        #     'project_path': project_path,
        #     'total_files_analyzed': len(self.all_results),
        #     'group_by_module': group_by_module,
        #     'random_seed': self.random_seed,
        #     'sampling_k': self.sampling_k,
        #     'all_results': self.all_results,
        #     'grouped_results': dict(self.grouped_results),
        #     'stratifications': all_stratifications,
        #     'sampling_results': all_sampling_results
        # }

        # return final_result

    def print_summary_report(self, final_result):
        """打印项目分析摘要报告"""
        print("\n" + "=" * 70)
        print("项目分析摘要报告")
        print("=" * 70)

        print(f"\n 项目基本信息:")
        print(f"  项目路径: {final_result['project_path']}")
        print(f"  分析文件总数: {final_result['total_files_analyzed']}")
        print(f"  是否按模块分组: {final_result['group_by_module']}")
        print(f"  随机种子: {final_result['random_seed']}")
        print(f"  每层抽样数量K: {final_result['sampling_k']}")

        # 显示全局得分分布
        if final_result['all_results']:
            scores = [r['score'] for r in final_result['all_results']]
            print(f"\n 全局得分分布:")
            print(f"  平均得分: {np.mean(scores):.4f}")
            print(f"  得分标准差: {np.std(scores):.4f}")
            print(f"  最低得分: {np.min(scores):.4f}")
            print(f"  最高得分: {np.max(scores):.4f}")

        # 显示每个组的抽样结果
        print(f"\n🔍 分层抽样结果:")
        for group_name, sampling_result in final_result['sampling_results'].items():
            print(f"\n  组: {group_name} (共{sampling_result['total_files']}个文件)")

            for tier_name, tier_info in sampling_result['tiers'].items():
                print(f"    {tier_info['tier_name']}:")
                print(f"      本层文件数: {tier_info['total_in_tier']}")
                print(f"      抽样数量: {tier_info['sampled_count']} ({tier_info['sampling_type']})")

                # 显示抽中的文件
                for i, file in enumerate(tier_info['sampled_files'], 1):
                    print(f"      {i}. {file['file_name']} (得分: {file['score']:.4f}, LOC: {file['loc']})")

    def export_results(self, final_result, output_dir="analysis_results1"):
        """将分析结果导出到文件"""
        os.makedirs(output_dir, exist_ok=True)

        # 1. 导出完整结果为JSON
        json_path = os.path.join(output_dir, "full_analysis.json")
        # 创建可序列化的字典（移除不可序列化的对象）
        export_dict = {
            'project_path': final_result['project_path'],
            'total_files_analyzed': final_result['total_files_analyzed'],
            'group_by_module': final_result['group_by_module'],
            'random_seed': final_result['random_seed'],
            'sampling_k': final_result['sampling_k'],
            'all_results': [
                {
                    'file_info': r['file_info'],
                    'raw_metrics': r['raw_metrics'],
                    'normalized_metrics': r['normalized_metrics'],
                    'score': r['score']
                }
                for r in final_result['all_results']
            ]
        }

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(export_dict, f, indent=2, ensure_ascii=False)

        # 2. 导出抽样结果为CSV
        import csv
        csv_path = os.path.join(output_dir, "sampled_files.csv")

        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['group', 'tier', 'file_name', 'file_path', 'score', 'loc', 'function_count']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for group_name, sampling_result in final_result['sampling_results'].items():
                for tier_name, tier_info in sampling_result['tiers'].items():
                    for file in tier_info['sampled_files']:
                        writer.writerow({
                            'group': group_name,
                            'tier': tier_name,
                            'file_name': file['file_name'],
                            'file_path': file['file_path'],
                            'score': file['score'],
                            'loc': file['loc'],
                            'function_count': file['function_count']
                        })

        # 3. 导出分层统计信息
        stats_path = os.path.join(output_dir, "stratification_stats.csv")

        with open(stats_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['group', 'tier', 'file_count', 'score_min', 'score_max', 'sampled_count']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for group_name, stratification in final_result['stratifications'].items():
                for tier_name in ['High', 'Mid', 'Low']:
                    tier = stratification[tier_name]
                    sampling_tier = final_result['sampling_results'][group_name]['tiers'][tier_name]

                    writer.writerow({
                        'group': group_name,
                        'tier': tier_name,
                        'file_count': tier['count'],
                        'score_min': tier['score_range'][0],
                        'score_max': tier['score_range'][1],
                        'sampled_count': sampling_tier['sampled_count']
                    })

        print(f"\n 分析结果已导出到目录: {output_dir}")
        print(f"  - 完整结果: {json_path}")
        print(f"  - 抽样文件列表: {csv_path}")
        print(f"  - 分层统计: {stats_path}")


# 使用示例
if __name__ == "__main__":
    project_dir = "projects/commons-cli/src"

    # 创建分析器实例
    analyzer = FileQualityAnalyzer(
        language="java",
        random_seed=42,  # 固定随机种子，确保结果可重复
        sampling_k=2  # 每个层级抽取2个文件
    )

    # 完整分析项目
    final_result = analyzer.analyze_project(
        project_path=project_dir,
        group_by_module=True  # 按模块分组
    )

    print(final_result)

    # if final_result:
    #     # 打印摘要报告
    #     analyzer.print_summary_report(final_result)

    #     # 导出结果
    #     analyzer.export_results(final_result)
