# import xml.etree.ElementTree as ET
# import csv
# import os
# from collections import defaultdict
# import sys
# import json
# from pathlib import Path

# def load_data_file(data_path, project_root):
#     """加载 data_file.json，返回文件路径集合和函数标识集合"""
#     with open(data_path, 'r', encoding='utf-8') as f:
#         data = json.load(f)

#     file_paths = set()
#     func_keys = set()
#     print(project_root)

#     for entry in data:
#         # print(entry.get("project_root", ''))
#         src_file = entry.get('src_file')
#         if not src_file:
#             continue
#         # project_root1 = entry.get('project_root').split(project_root)[-1].split('/', 1)[-1]  # 提取相对路径
#         # src_file = os.path.join(project_root1, src_file)
#         src_file = src_file.replace('src/main/java/', '')
#         file_paths.add(src_file)

#         name = entry.get('name', '')
#         class_name = entry.get('class_name')
#         if class_name:
#             func_name = f"{class_name}.{name}"
#         else:
#             func_name = name
#         func_key = f"{src_file}:{func_name}"
#         func_keys.add(func_key)

#     return file_paths, func_keys

# def parse_jacoco_xml(xml_path, output_methods='function_coverage.csv', output_files='file_coverage.csv'):
#     """
#     解析JaCoCo XML报告，提取方法级和文件级行/分支覆盖率。
    
#     Args:
#         xml_path (str): jacoco.xml文件路径
#         output_methods (str): 输出的方法级CSV文件名
#         output_files (str): 输出的文件级CSV文件名
#     """
#     tree = ET.parse(xml_path)
#     root = tree.getroot()

#     # 存储方法级数据
#     methods_data = []
#     # 存储文件级行覆盖率（从<sourcefile>解析）
#     file_line_coverage = {}
#     # 存储文件级分支覆盖率（从<class>累加）
#     file_branch_coverage = defaultdict(lambda: {'missed': 0, 'covered': 0})

#     # 遍历所有package
#     for package in root.findall('package'):
#         package_name = package.get('name')  # 如 "org/apache/commons/cli/help"

#         # --- 处理每个<class>，提取方法级数据，并累加分⽀到文件级 ---
#         for cls in package.findall('class'):
#             source_file = cls.get('sourcefilename')
#             if source_file:
#                 file_key = f"{package_name}/{source_file}"  # 用包路径+文件名作为唯一键

#                 # 累加该类的分支覆盖率（用于文件级）
#                 branch_counter = cls.find("./counter[@type='BRANCH']")
#                 if branch_counter is not None:
#                     file_branch_coverage[file_key]['missed'] += int(branch_counter.get('missed'))
#                     file_branch_coverage[file_key]['covered'] += int(branch_counter.get('covered'))

#                 # 处理该类下的每个方法
#                 for method in cls.findall('method'):
#                     method_name = method.get('name')
#                     method_desc = method.get('desc')  # 方法描述，用于区分重载

#                     # 方法行覆盖率
#                     line_counter = method.find("./counter[@type='LINE']")
#                     if line_counter is not None:
#                         line_missed = int(line_counter.get('missed'))
#                         line_covered = int(line_counter.get('covered'))
#                     else:
#                         line_missed = line_covered = 0

#                     # 方法分支覆盖率
#                     branch_counter_m = method.find("./counter[@type='BRANCH']")
#                     if branch_counter_m is not None:
#                         branch_missed = int(branch_counter_m.get('missed'))
#                         branch_covered = int(branch_counter_m.get('covered'))
#                     else:
#                         branch_missed = branch_covered = 0

#                     methods_data.append({
#                         'package': package_name.replace('/', '.'),
#                         'class': cls.get('name').replace('/', '.'),
#                         'method': method_name,
#                         'desc': method_desc,
#                         'line_missed': line_missed,
#                         'line_covered': line_covered,
#                         'branch_missed': branch_missed,
#                         'branch_covered': branch_covered
#                     })

#         # --- 处理<sourcefile>，获取文件级行覆盖率 ---
#         for sourcefile in package.findall('sourcefile'):
#             sourcefile_name = sourcefile.get('name')
#             file_key = f"{package_name}/{sourcefile_name}"

#             # 统计该文件中的行覆盖
#             total_lines = 0
#             covered_lines = 0
#             for line in sourcefile.findall('line'):
#                 total_lines += 1
#                 ci = int(line.get('ci', 0))
#                 if ci > 0:  # 只要该行有指令被覆盖，即视为已覆盖
#                     covered_lines += 1

#             file_line_coverage[file_key] = {
#                 'total_lines': total_lines,
#                 'covered_lines': covered_lines,
#                 'missed_lines': total_lines - covered_lines
#             }

#     # --- 合并文件级数据（行覆盖 + 分支覆盖） ---
#     # 最终文件级列表
#     file_data = []
#     # 所有出现在<sourcefile>中的文件（可能会有部分文件没有分支，但需要输出）
#     all_file_keys = set(file_line_coverage.keys()) | set(file_branch_coverage.keys())
#     for file_key in sorted(all_file_keys):
#         # 行覆盖
#         line_info = file_line_coverage.get(file_key, {'total_lines': 0, 'covered_lines': 0, 'missed_lines': 0})
#         total_lines = line_info['total_lines']
#         covered_lines = line_info['covered_lines']
#         missed_lines = line_info['missed_lines']

#         # 分支覆盖
#         branch_info = file_branch_coverage.get(file_key, {'missed': 0, 'covered': 0})
#         branch_missed = branch_info['missed']
#         branch_covered = branch_info['covered']
#         total_branches = branch_missed + branch_covered

#         # 计算百分比
#         line_coverage_percent = (covered_lines / total_lines * 100) if total_lines > 0 else 0
#         branch_coverage_percent = (branch_covered / total_branches * 100) if total_branches > 0 else 0

#         file_data.append({
#             'file': file_key,
#             'line_missed': missed_lines,
#             'line_covered': covered_lines,
#             'total_lines': total_lines,
#             'line_coverage': f"{line_coverage_percent:.2f}",
#             'branch_missed': branch_missed,
#             'branch_covered': branch_covered,
#             'total_branches': total_branches,
#             'branch_coverage': f"{branch_coverage_percent:.2f}"
#         })

#     method_line_total = sum(m['line_missed'] + m['line_covered'] for m in methods_data)
#     method_line_covered = sum(m['line_covered'] for m in methods_data)
#     overall_line_coverage = (method_line_covered / method_line_total * 100) if method_line_total > 0 else 0
#     method_branch_total = sum(m['branch_missed'] + m['branch_covered'] for m in methods_data)
#     method_branch_covered = sum(m['branch_covered'] for m in methods_data)
#     overall_branch_coverage = (method_branch_covered / method_branch_total * 100) if method_branch_total > 0 else 0
#     file_line_total = sum(f['total_lines'] for f in file_data)
#     file_line_covered = sum(f['line_covered'] for f in file_data)
#     overall_file_line_coverage = (file_line_covered / file_line_total * 100) if file_line_total > 0 else 0
#     file_branch_total = sum(f['total_branches'] for f in file_data)
#     file_branch_covered = sum(f['branch_covered'] for f in file_data)
#     overall_file_branch_coverage = (file_branch_covered / file_branch_total * 100) if file_branch_total > 0 else 0
#     # --- 写入方法级CSV ---
#     with open(output_methods, 'w', newline='', encoding='utf-8') as f:
#         writer = csv.writer(f)
#         writer.writerow(['Package', 'Class', 'Method', 'Desc', 
#                          'Line_Missed', 'Line_Covered', 'Branch_Missed', 'Branch_Covered'])
#         for m in methods_data:
#             writer.writerow([
#                 m['package'], m['class'], m['method'], m['desc'],
#                 m['line_missed'], m['line_covered'],
#                 m['branch_missed'], m['branch_covered']
#             ])
#         writer.writerow([method_line_total, method_line_covered, overall_line_coverage, method_branch_total, method_branch_covered, overall_branch_coverage])

#     # --- 写入文件级CSV ---
#     with open(output_files, 'w', newline='', encoding='utf-8') as f:
#         writer = csv.writer(f)
#         writer.writerow(['File', 'Line_Missed', 'Line_Covered', 'Total_Lines', 'Line_Coverage%',
#                          'Branch_Missed', 'Branch_Covered', 'Total_Branches', 'Branch_Coverage%'])
#         for file in file_data:
#             writer.writerow([
#                 file['file'],
#                 file['line_missed'], file['line_covered'], file['total_lines'], file['line_coverage'],
#                 file['branch_missed'], file['branch_covered'], file['total_branches'], file['branch_coverage']
#             ])
#         writer.writerow(['Total', '', file_line_covered, file_line_total, overall_file_line_coverage, '', file_branch_covered, file_branch_total, overall_file_branch_coverage])

#     print(f"完成！已生成 {output_methods} 和 {output_files}")

# def list_first_level_dirs(target_dir: str = ".") -> list:
#     """
#     返回 target_dir 下的所有第一级子目录路径列表。
#     """
#     path = Path(target_dir)
    
#     # 检查路径是否存在且是一个目录
#     if not path.exists():
#         print(f"错误：路径 '{target_dir}' 不存在。", file=sys.stderr)
#         return []
#     if not path.is_dir():
#         print(f"错误：'{target_dir}' 不是一个目录。", file=sys.stderr)
#         return []
    
#     # 收集所有子目录
#     subdirs = [entry for entry in path.iterdir() if entry.is_dir()]
#     return subdirs

# if __name__ == '__main__':
#     # 请将下面的路径替换为您的jacoco.xml文件路径
#     # subdir = list_first_level_dirs("test_results/commons-cli/")
#     # for d in subdir:
#     #     xml_file = os.path.join(d, "target_jacoco.xml")
#     #     output_methods_file = os.path.join(d, "function_coverage.csv")
#     #     output_files_file = os.path.join(d, "file_coverage.csv")
#     #     parse_jacoco_xml(xml_file, output_methods_file, output_files_file)

#     xml_file = 'test_results/java/nfe/specification_junit5_gpt4o/target_jacoco.xml'  # 如果与脚本在同一目录，直接写文件名
#     output_methods_file = 'test_results/java/nfe/specification_junit5_gpt4o/function_coverage.csv'
#     output_files_file = 'test_results/java/nfe/specification_junit5_gpt4o/file_coverage.csv'
#     parse_jacoco_xml(xml_file, output_methods_file, output_files_file)


import xml.etree.ElementTree as ET
import csv
import os
from collections import defaultdict
import sys
import json
from pathlib import Path

# def src_file_to_file_key(src_file):
#     """
#     将 JSON 中的 src_file 转换为 JaCoCo XML 中的文件标识。
#     例如："src/main/java/org/apache/commons/cli/help/TextHelpAppendable.java"
#     转换为 "org/apache/commons/cli/help/TextHelpAppendable.java"
#     """
#     prefix = "src/main/java/"
#     if src_file.startswith(prefix):
#         return src_file[len(prefix):]
#     return src_file

def src_file_to_file_key(src_file):
    marker = "src/main/java/"
    idx = src_file.find(marker)
    if idx != -1:
        return src_file[idx + len(marker):]
    return src_file

def load_filter_data(json_path):
    """
    从 JSON 文件中提取需要保留的文件标识和方法标识。
    返回 (file_keys_set, method_keys_set)
        file_keys_set: 需要保留的文件标识（如 "org/apache/commons/cli/help/TextHelpAppendable.java"）
        method_keys_set: 需要保留的 (file_key, method_name) 元组集合
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    file_keys = set()
    method_keys = set()

    for item in data:
        src_file = item.get('src_file')
        method_name = item.get('name')
        if src_file:
            file_key = src_file_to_file_key(src_file)
            file_keys.add(file_key)
            if method_name:
                method_keys.add((file_key, method_name))
    return file_keys, method_keys

def parse_jacoco_xml(xml_path, filter_json_path=None, output_json=None):
    """
    解析JaCoCo XML报告，提取方法级和文件级行/分支覆盖率。
    如果提供 filter_json_path，则只输出该 JSON 中指定的文件/方法覆盖率。
    如果提供 output_json，则额外生成一个 JSON 文件保存详细覆盖率。

    Args:
        xml_path (str): jacoco.xml文件路径
        output_methods (str): 输出的方法级CSV文件名
        output_files (str): 输出的文件级CSV文件名
        filter_json_path (str): 可选，过滤用的 JSON 文件路径
        output_json (str): 可选，输出 JSON 文件的路径
    """
    if not os.path.exists(xml_path):
        return {}
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # 加载过滤数据（如果有）
    file_filter = None
    method_filter = None
    if filter_json_path:
        file_filter, method_filter = load_filter_data(filter_json_path)
        print(f"已加载过滤文件数: {len(file_filter)}，过滤方法数: {len(method_filter)}")

    # 存储方法级数据
    methods_data = []
    # 存储文件级行覆盖率（从<sourcefile>解析）
    file_line_coverage = {}
    # 存储文件级分支覆盖率（从<class>累加）
    file_branch_coverage = defaultdict(lambda: {'missed': 0, 'covered': 0})

    # 遍历所有package
    for package in root.findall('package'):
        package_name = package.get('name')  # 如 "org/apache/commons/cli/help"

        # --- 处理每个<class>，提取方法级数据，并累加分⽀到文件级 ---
        for cls in package.findall('class'):
            source_file = cls.get('sourcefilename')
            if source_file:
                file_key = f"{package_name}/{source_file}"  # 唯一文件标识

                # 如果设置了文件过滤，且该文件不在过滤集合中，则跳过整个类
                if file_filter is not None and file_key not in file_filter:
                    continue

                # 累加该类的分支覆盖率（用于文件级）
                branch_counter = cls.find("./counter[@type='BRANCH']")
                if branch_counter is not None:
                    file_branch_coverage[file_key]['missed'] += int(branch_counter.get('missed'))
                    file_branch_coverage[file_key]['covered'] += int(branch_counter.get('covered'))

                # 处理该类下的每个方法
                for method in cls.findall('method'):
                    method_name = method.get('name')
                    method_desc = method.get('desc')  # 方法描述，用于区分重载

                    # 如果设置了方法过滤，且 (file_key, method_name) 不在过滤集合中，则跳过
                    if method_filter is not None and (file_key, method_name) not in method_filter:
                        continue

                    # 方法行覆盖率
                    line_counter = method.find("./counter[@type='LINE']")
                    if line_counter is not None:
                        line_missed = int(line_counter.get('missed'))
                        line_covered = int(line_counter.get('covered'))
                    else:
                        line_missed = line_covered = 0

                    # 方法分支覆盖率
                    branch_counter_m = method.find("./counter[@type='BRANCH']")
                    if branch_counter_m is not None:
                        branch_missed = int(branch_counter_m.get('missed'))
                        branch_covered = int(branch_counter_m.get('covered'))
                    else:
                        branch_missed = branch_covered = 0

                    # 构建方法唯一标识（用于 JSON 中的键，使用类名.方法名）
                    class_name = cls.get('name').replace('/', '.')
                    method_key = f"{class_name}.{method_name}"
                    # 但如果需要保持原始简单 method_name 作为键，可以修改下面，但为了避免覆盖，建议使用 class.method
                    # 这里我们按照用户示例使用 method_name 作为键，同时保存 class 信息以备参考（但不在 JSON 中体现）
                    methods_data.append({
                        'package': package_name.replace('/', '.'),
                        'class': class_name,
                        'method': method_name,
                        'desc': method_desc,
                        'line_missed': line_missed,
                        'line_covered': line_covered,
                        'branch_missed': branch_missed,
                        'branch_covered': branch_covered
                    })

        # --- 处理<sourcefile>，获取文件级行覆盖率 ---
        for sourcefile in package.findall('sourcefile'):
            sourcefile_name = sourcefile.get('name')
            file_key = f"{package_name}/{sourcefile_name}"

            # 如果设置了文件过滤，且该文件不在过滤集合中，则跳过
            if file_filter is not None and file_key not in file_filter:
                continue

            # 统计该文件中的行覆盖
            total_lines = 0
            covered_lines = 0
            for line in sourcefile.findall('line'):
                total_lines += 1
                ci = int(line.get('ci', 0))
                if ci > 0:  # 只要该行有指令被覆盖，即视为已覆盖
                    covered_lines += 1

            file_line_coverage[file_key] = {
                'total_lines': total_lines,
                'covered_lines': covered_lines,
                'missed_lines': total_lines - covered_lines
            }

    # --- 合并文件级数据（行覆盖 + 分支覆盖） ---
    file_data = []
    all_file_keys = set(file_line_coverage.keys()) | set(file_branch_coverage.keys())
    if file_filter is not None:
        output_file_keys = file_filter & all_file_keys
    else:
        output_file_keys = all_file_keys

    for file_key in sorted(output_file_keys):
        line_info = file_line_coverage.get(file_key, {'total_lines': 0, 'covered_lines': 0, 'missed_lines': 0})
        total_lines = line_info['total_lines']
        covered_lines = line_info['covered_lines']
        missed_lines = line_info['missed_lines']

        branch_info = file_branch_coverage.get(file_key, {'missed': 0, 'covered': 0})
        branch_missed = branch_info['missed']
        branch_covered = branch_info['covered']
        total_branches = branch_missed + branch_covered

        line_coverage_percent = (covered_lines / total_lines * 100) if total_lines > 0 else 0
        branch_coverage_percent = (branch_covered / total_branches * 100) if total_branches > 0 else 0

        file_data.append({
            'file': file_key,
            'line_missed': missed_lines,
            'line_covered': covered_lines,
            'total_lines': total_lines,
            'line_coverage': f"{line_coverage_percent:.2f}",
            'branch_missed': branch_missed,
            'branch_covered': branch_covered,
            'total_branches': total_branches,
            'branch_coverage': f"{branch_coverage_percent:.2f}"
        })

    # 计算汇总统计
    method_line_total = sum(m['line_missed'] + m['line_covered'] for m in methods_data)
    method_line_covered = sum(m['line_covered'] for m in methods_data)
    overall_line_coverage = (method_line_covered / method_line_total * 100) if method_line_total > 0 else 0
    method_branch_total = sum(m['branch_missed'] + m['branch_covered'] for m in methods_data)
    method_branch_covered = sum(m['branch_covered'] for m in methods_data)
    overall_branch_coverage = (method_branch_covered / method_branch_total * 100) if method_branch_total > 0 else 0

    file_line_total = sum(f['total_lines'] for f in file_data)
    file_line_covered = sum(f['line_covered'] for f in file_data)
    overall_file_line_coverage = (file_line_covered / file_line_total * 100) if file_line_total > 0 else 0
    file_branch_total = sum(f['total_branches'] for f in file_data)
    file_branch_covered = sum(f['branch_covered'] for f in file_data)
    overall_file_branch_coverage = (file_branch_covered / file_branch_total * 100) if file_branch_total > 0 else 0

    # # --- 写入方法级CSV ---
    # with open(output_methods, 'w', newline='', encoding='utf-8') as f:
    #     writer = csv.writer(f)
    #     writer.writerow(['Package', 'Class', 'Method', 'Desc', 
    #                      'Line_Missed', 'Line_Covered', 'Branch_Missed', 'Branch_Covered'])
    #     for m in methods_data:
    #         writer.writerow([
    #             m['package'], m['class'], m['method'], m['desc'],
    #             m['line_missed'], m['line_covered'],
    #             m['branch_missed'], m['branch_covered']
    #         ])
    #     writer.writerow(['TOTAL', '', '', '', 
    #                      method_line_total, method_line_covered, 
    #                      method_branch_total, method_branch_covered,
    #                      f"{overall_line_coverage:.2f}%", f"{overall_branch_coverage:.2f}%"])

    # # --- 写入文件级CSV ---
    # with open(output_files, 'w', newline='', encoding='utf-8') as f:
    #     writer = csv.writer(f)
    #     writer.writerow(['File', 'Line_Missed', 'Line_Covered', 'Total_Lines', 'Line_Coverage%',
    #                      'Branch_Missed', 'Branch_Covered', 'Total_Branches', 'Branch_Coverage%'])
    #     for file in file_data:
    #         writer.writerow([
    #             file['file'],
    #             file['line_missed'], file['line_covered'], file['total_lines'], file['line_coverage'],
    #             file['branch_missed'], file['branch_covered'], file['total_branches'], file['branch_coverage']
    #         ])
    #     writer.writerow(['Total', '', file_line_covered, file_line_total, f"{overall_file_line_coverage:.2f}",
    #                      '', file_branch_covered, file_branch_total, f"{overall_file_branch_coverage:.2f}"])

    # --- 生成JSON文件---
    # if output_json:
    # 构建 file_coverage 部分
    file_coverage_json = {}
    for f in file_data:
        file_coverage_json[f['file']] = {
            'total_line': f['total_lines'],
            'covered_line': f['line_covered'],
            'total_branch': f['total_branches'],
            'covered_branch': f['branch_covered']
        }

    # 构建 function_coverage 部分，使用 method_name 作为键（可能存在重名覆盖，这里按用户示例）
    function_coverage_json = {}
    for m in methods_data:
        class_name = m['class']
        method_name = m['method']
        # 如果方法名重复，后面的会覆盖前面的（按 JSON 规范，键必须唯一）
        # 为了更精确，可以改为 class.method，但用户示例是 method_name，故先这样
        function_coverage_json[f"{class_name}.{method_name}"] = {
            'total_line': m['line_missed'] + m['line_covered'],
            'covered_line': m['line_covered'],
            'total_branch': m['branch_missed'] + m['branch_covered'],
            'covered_branch': m['branch_covered']
        }

    # 构建 filtered_stats 部分
    filtered_stats = {
        'file': {
            'total_lines': file_line_total,
            'covered_lines': file_line_covered,
            'total_branches': file_branch_total,
            'covered_branches': file_branch_covered
        },
        'function': {
            'total_lines': method_line_total,
            'covered_lines': method_line_covered,
            'total_branches': method_branch_total,
            'covered_branches': method_branch_covered
        }
    }

    # 组装最终 JSON
    result_json = {
        'file_coverage': file_coverage_json,
        'function_coverage': function_coverage_json,
        'summary': filtered_stats
    }
        # 'filtered_stats': filtered_stats
        
    # return result_json
        # 写入 JSON 文件
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(result_json, f, indent=2, ensure_ascii=False)

    #     print(f"完成！已生成 {output_json}")

    # print(f"完成！已生成 {output_methods} 和 {output_files}")

def list_first_level_dirs(target_dir: str = ".") -> list:
    """
    返回 target_dir 下的所有第一级子目录路径列表。
    """
    path = Path(target_dir)
    if not path.exists():
        print(f"错误：路径 '{target_dir}' 不存在。", file=sys.stderr)
        return []
    if not path.is_dir():
        print(f"错误：'{target_dir}' 不是一个目录。", file=sys.stderr)
        return []
    subdirs = [entry for entry in path.iterdir() if entry.is_dir()]
    return subdirs

if __name__ == '__main__':
    xml_file = 'test_results/java/flink/src_src_junit5_copilot_gpt-5.6-luna/flink-core_target_jacoco.xml'
    # output_methods_file = 'xx/function_coverage.csv'
    # output_files_file = 'xx/file_coverage.csv'
    filter_json = 'test_results/java/flink/junit5_agent/copilot_testgen_results.json'              # 过滤用的 JSON 文件，若无则设为 None
    output_json_file = 'test_results/java/flink/src_src_junit5_copilot_gpt-5.6-luna/coverage_summary2.json'  # 输出的 JSON 文件路径

    # 调用解析函数
    parse_jacoco_xml(
        xml_path=xml_file,
        # output_methods=output_methods_file,
        # output_files=output_files_file,
        filter_json_path=filter_json if Path(filter_json).exists() else None,
        output_json=output_json_file
    )