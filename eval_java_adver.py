import subprocess
import os
import json
import tempfile
import xml.etree.ElementTree as ET
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor, as_completed

import csv

from pathlib import Path
from collections import defaultdict


BASE_DIR = Path(__file__).resolve().parent


def syntax_analyse(data_file):
    import javalang

    with open(data_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    total = 0
    syntax_correct = 0

    for item in data:
        test_code = item.get("generated_tests", "")
        for test in test_code:
            if not test.strip():
                continue

            total += 1
            try:
                javalang.parse.parse(test)
                syntax_correct += 1
            except Exception as e:
                pass

    return {"total": total, "syntax_correct": syntax_correct, "syntax_correct_rate": syntax_correct / total}


def calculate_test_pass_rate(report_dir):
    """解析 /results/reports 下所有的 JUnit XML"""
    total = 0
    passed = 0
    failures = 0
    errors = 0

    if not os.path.exists(report_dir):
        return {"total": 0, "passed": 0, "failures": 0, "errors": 0, "pass_rate": 0}

    for filename in os.listdir(report_dir):
        if filename.endswith(".xml"):
            try:
                tree = ET.parse(os.path.join(report_dir, filename))
                root = tree.getroot()
                # 有些报告 root 是 testsuite，有些是 testsuites
                suites = [root] if root.tag == 'testsuite' else root.findall('testsuite')
                for suite in suites:
                    total += int(suite.attrib.get('tests', 0))
                    failures += int(suite.attrib.get('failures', 0))
                    errors += int(suite.attrib.get('errors', 0))
            except Exception as e:
                print(f"解析 {filename} 失败: {e}")

    passed = total - failures - errors
    pass_rate = (passed / total) if total > 0 else 0
    return {
        "total": total,
        "passed": passed,
        "failures": failures,
        "errors": errors,
        "pass_rate": pass_rate
    }




def get_coverage_rates(xml_path, output_methods='function_coverage.csv', output_files='file_coverage.csv'):
    """
    解析JaCoCo XML报告，提取方法级和文件级行/分支覆盖率。
    
    Args:
        xml_path (str): jacoco.xml文件路径
        output_methods (str): 输出的方法级CSV文件名
        output_files (str): 输出的文件级CSV文件名
    """
    if not os.path.exists(xml_path):
        return 

    tree = ET.parse(xml_path)
    root = tree.getroot()

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
                file_key = f"{package_name}/{source_file}"  # 用包路径+文件名作为唯一键

                # 累加该类的分支覆盖率（用于文件级）
                branch_counter = cls.find("./counter[@type='BRANCH']")
                if branch_counter is not None:
                    file_branch_coverage[file_key]['missed'] += int(branch_counter.get('missed'))
                    file_branch_coverage[file_key]['covered'] += int(branch_counter.get('covered'))

                # 处理该类下的每个方法
                for method in cls.findall('method'):
                    method_name = method.get('name')
                    method_desc = method.get('desc')  # 方法描述，用于区分重载

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

                    methods_data.append({
                        'package': package_name.replace('/', '.'),
                        'class': cls.get('name').replace('/', '.'),
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
    # 最终文件级列表
    file_data = []
    # 所有出现在<sourcefile>中的文件（可能会有部分文件没有分支，但需要输出）
    all_file_keys = set(file_line_coverage.keys()) | set(file_branch_coverage.keys())
    for file_key in sorted(all_file_keys):
        # 行覆盖
        line_info = file_line_coverage.get(file_key, {'total_lines': 0, 'covered_lines': 0, 'missed_lines': 0})
        total_lines = line_info['total_lines']
        covered_lines = line_info['covered_lines']
        missed_lines = line_info['missed_lines']

        # 分支覆盖
        branch_info = file_branch_coverage.get(file_key, {'missed': 0, 'covered': 0})
        branch_missed = branch_info['missed']
        branch_covered = branch_info['covered']
        total_branches = branch_missed + branch_covered

        # 计算百分比
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
    # --- 写入方法级CSV ---
    with open(output_methods, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Package', 'Class', 'Method', 'Desc', 
                         'Line_Missed', 'Line_Covered', 'Branch_Missed', 'Branch_Covered'])
        for m in methods_data:
            writer.writerow([
                m['package'], m['class'], m['method'], m['desc'],
                m['line_missed'], m['line_covered'],
                m['branch_missed'], m['branch_covered']
            ])
        writer.writerow([method_line_total, method_line_covered, overall_line_coverage, method_branch_total, method_branch_covered, overall_branch_coverage])

    # --- 写入文件级CSV ---
    with open(output_files, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['File', 'Line_Missed', 'Line_Covered', 'Total_Lines', 'Line_Coverage%',
                         'Branch_Missed', 'Branch_Covered', 'Total_Branches', 'Branch_Coverage%'])
        for file in file_data:
            writer.writerow([
                file['file'],
                file['line_missed'], file['line_covered'], file['total_lines'], file['line_coverage'],
                file['branch_missed'], file['branch_covered'], file['total_branches'], file['branch_coverage']
            ])
        writer.writerow(['Total', '', file_line_covered, file_line_total, overall_file_line_coverage, '', file_branch_covered, file_branch_total, overall_file_branch_coverage])

    print(f"完成！已生成 {output_methods} 和 {output_files}")

def parse_junit_xml(report_dir):
    """解析 JUnit XML 报告以获取编译/通过率"""
    total_tests = 0
    failures = 0
    errors = 0

    # 遍历目录下所有的 XML 测试报告
    if not os.path.exists(report_dir):
        return {"compile_status": "failed", "pass_rate": 0}

    for filename in os.listdir(report_dir):
        if filename.endswith(".xml") and filename.startswith("TEST-"):
            tree = ET.parse(os.path.join(report_dir, filename))
            root = tree.getroot()
            total_tests += int(root.attrib.get('tests', 0))
            failures += int(root.attrib.get('failures', 0))
            errors += int(root.attrib.get('errors', 0))

    passed = total_tests - failures - errors
    pass_rate = (passed / total_tests) if total_tests > 0 else 0
    return {
        "total": total_tests,
        "passed": passed,
        "failures": failures,
        "errors": errors,
        "pass_rate": pass_rate
    }


def parse_jacoco_csv(csv_path):
    """解析 JaCoCo CSV 报告获取覆盖率"""
    if not os.path.exists(csv_path):
        return {"line_coverage": 0, "branch_coverage": 0}

    # JaCoCo CSV 结构: [0]GROUP, [1]PACKAGE, [2]CLASS, [3]INSTRUCTION_MISSED, [4]INSTRUCTION_COVERED...
    # [5]BRANCH_MISSED, [6]BRANCH_COVERED, [7]LINE_MISSED, [8]LINE_COVERED...
    try:
        missed_lines = 0
        covered_lines = 0
        missed_branches = 0
        covered_branches = 0

        with open(csv_path, 'r') as f:
            lines = f.readlines()[1:]  # 跳过表头
            for line in lines:
                parts = line.split(',')
                missed_branches += int(parts[5])
                covered_branches += int(parts[6])
                missed_lines += int(parts[7])
                covered_lines += int(parts[8])

        line_cov = covered_lines / (covered_lines + missed_lines) if (covered_lines + missed_lines) > 0 else 0
        branch_cov = covered_branches / (covered_branches + missed_branches) if (
                                                                                            covered_branches + missed_branches) > 0 else 0

        return {
            "line_coverage": line_cov,
            "branch_coverage": branch_cov
        }
    except Exception as e:
        print(f"解析覆盖率失败: {e}")
        return {"line_coverage": 0, "branch_coverage": 0}


def get_compiled_tests_count(test_results_dir):
    """读取成功编译的测试文件数量"""
    count_file = os.path.join(test_results_dir, "compiled_tests_count.txt")

    if os.path.exists(count_file):
        try:
            with open(count_file, 'r') as f:
                count = int(f.read().strip())
            return count
        except (ValueError, IOError) as e:
            print(f"读取编译测试计数失败: {e}")
            return 0
    else:
        print("未找到编译测试计数文件")
        return 0


def resolve_dockerfile(dockerfile_path, repo_name):
    """解析项目 Dockerfile。

    显式路径优先；未指定时在 dockerfiles/<repo-name>/ 下递归查找。
    只有唯一候选时才自动选择，防止多个镜像配置时静默用错。
    """
    if dockerfile_path:
        dockerfile = Path(dockerfile_path)
        if not dockerfile.is_absolute():
            dockerfile = BASE_DIR / dockerfile
        dockerfile = dockerfile.resolve()
        if not dockerfile.is_file():
            raise FileNotFoundError(f"Dockerfile 不存在: {dockerfile}")
        return dockerfile

    project_docker_dir = BASE_DIR / "dockerfiles" / repo_name
    preferred = [
        project_docker_dir / "Dockerfile",
        project_docker_dir / repo_name / "Dockerfile",
    ]
    for candidate in preferred:
        if candidate.is_file():
            return candidate.resolve()
    candidates = sorted(project_docker_dir.rglob("Dockerfile")) \
        if project_docker_dir.is_dir() else []
    if len(candidates) == 1:
        return candidates[0].resolve()
    if not candidates:
        # Repositories are sometimes grouped one level below dockerfiles/
        # (for example dockerfiles/parquet/parquet-java/Dockerfile). Match
        # the project directory name without hard-coding any repository.
        nested = sorted(
            path for path in (BASE_DIR / "dockerfiles").rglob("Dockerfile")
            if path.parent.name == repo_name)
        if len(nested) == 1:
            return nested[0].resolve()
        if not nested:
            raise FileNotFoundError(
                f"未在 {project_docker_dir} 或 dockerfiles 的嵌套目录中找到 Dockerfile；"
                "请使用 --dockerfile 显式指定")
        formatted = "\n  ".join(str(path) for path in nested)
        raise RuntimeError(
            f"项目 {repo_name} 存在多个嵌套 Dockerfile，请使用 --dockerfile 选择:\n  {formatted}")
    formatted = "\n  ".join(str(path) for path in candidates)
    raise RuntimeError(
        f"项目 {repo_name} 存在多个 Dockerfile，请使用 --dockerfile 选择:\n  {formatted}")


def create_and_run_java(dockerfile_path, repo_dir, data_file, *,
                        bug_model="gpt-5-nano",
                        judge_model="gpt-5-nano",
                        filter_model_a="gpt-5-nano",
                        filter_model_b="qwen3.5-flash",
                        attempts=3,
                        suite_retries=1,
                        qwen_api_endpoint=None,
                        test_agent="mini-swe",
                        test_agent_steps=100,
                        test_agent_timeout=1200,
                        start_index=0,
                        limit=0,
                        workers=1,
                        config_files=None):
    """构建项目镜像并在容器内运行错误代码构造流程。

    所有宿主机路径都相对于本脚本所在目录解析，不再依赖调用者的
    当前工作目录。workers>1 时，每个函数使用独立容器和结果目录，
    防止临时源码/测试文件修改互相污染。
    """
    repo_name = Path(repo_dir).name
    if not repo_name:
        raise ValueError(f"无法从 repo_dir 推导项目名: {repo_dir!r}")
    dockerfile = resolve_dockerfile(dockerfile_path, repo_name)
    data_path = Path(data_file)
    if not data_path.is_absolute():
        data_path = BASE_DIR / data_path

    data_path = data_path.resolve()
    if not data_path.is_file():
        raise FileNotFoundError(f"数据文件不存在: {data_path}")
    if not os.getenv("GPT_API_KEY"):
        raise RuntimeError("请先设置 GPT_API_KEY；密钥不再从代码内置值回退")
    model_b_uses_gpt = str(filter_model_b).strip().lower().startswith(("gpt-", "openai/gpt-"))
    if not model_b_uses_gpt and not os.getenv("QWEN_API_KEY"):
        raise RuntimeError("请先设置 QWEN_API_KEY；密钥不再从代码内置值回退")
    if workers < 1:
        raise ValueError("workers 必须 >= 1")
    if start_index < 0 or limit < 0:
        raise ValueError("start_index 和 limit 必须 >= 0")
    if test_agent_steps < 1 or test_agent_timeout < 1:
        raise ValueError("test_agent_steps 和 test_agent_timeout 必须 >= 1")

    image_name = f"java-repo-{repo_name.lower()}"
    config_mounts = []
    for host_path, project_path in config_files or []:
        source = Path(host_path)
        if not source.is_absolute():
            source = BASE_DIR / source
        source = source.resolve()
        if not source.is_file():
            raise FileNotFoundError(f"复用配置文件不存在: {source}")
        destination = Path(project_path)
        if destination.is_absolute() or ".." in destination.parts:
            raise ValueError(f"容器内配置路径必须是安全的项目相对路径: {project_path}")
        config_mounts.append((source, f"/testbed/{destination.as_posix()}"))

    print(f"工作区目录: {BASE_DIR}")

    # 1. 准备目录
    test_results_dir = BASE_DIR / "test_results" / "java" / repo_name / "adver_100"

    test_results_dir.mkdir(parents=True, exist_ok=True)

    # syntax_report = syntax_analyse(data_file)

    # 2. 构建镜像
    print("开始构建 Java 项目镜像...")
    try:
        subprocess.run([
            "docker", "build",
            "-t", image_name,
            "-f", str(dockerfile),
            str(BASE_DIR)
        ], check=True)
    except subprocess.CalledProcessError as e:
        print(f"镜像构建失败: {e}")
        raise

    # 3. 构造独立容器命令。每个 docker run 都基于同一镜像但拥有独立
    # 可写层，因此项目源码、测试文件和 Maven target 不会跨函数共享。
    scripts = {
        "adver_dual.py": "adver.py",
        "test_gen.py": "test_gen.py",
        "filter_test_gen.py": "filter_test_gen.py",
        "mini_swe_test_agent.py": "mini_swe_test_agent.py",
        "bug_generation_agent.py": "bug_generation_agent.py",
        "llm_config.py": "llm_config.py",
        "usage_tracker.py": "usage_tracker.py",
        "valid_agent.py": "valid_agent.py",
    }
    script_paths = {}
    for source_name, target_name in scripts.items():
        source = (BASE_DIR / "AdverBug" / source_name).resolve()
        if not source.is_file():
            raise FileNotFoundError(f"容器运行脚本不存在: {source}")
        script_paths[target_name] = source

    def docker_command(entry_data_path, entry_results_dir, *, entry_start_index=0,
                       entry_limit=0):
        command = ["docker", "run", "--rm", "-v", f"{entry_results_dir}:/results"]
        for source, destination in config_mounts:
            command.extend(["-v", f"{source}:{destination}:ro"])
        for target_name, source in script_paths.items():
            command.extend(["-v", f"{source}:/testbed/{target_name}:ro"])
        command.extend(["-v", f"{entry_data_path}:/testbed/adver_input.json:ro"])
        # 只传递环境变量名，避免密钥出现在命令行和日志中。
        command.extend(["-e", "GPT_API_KEY"])
        if os.getenv("QWEN_API_KEY"):
            command.extend(["-e", "QWEN_API_KEY"])
        if os.getenv("GPT_API_ENDPOINT"):
            command.extend(["-e", "GPT_API_ENDPOINT"])
        if os.getenv("QWEN_API_ENDPOINT"):
            command.extend(["-e", "QWEN_API_ENDPOINT"])
        if os.getenv("LLM_REQUEST_TIMEOUT"):
            command.extend(["-e", "LLM_REQUEST_TIMEOUT"])
        if os.getenv("LLM_MODEL_PRICING_JSON"):
            command.extend(["-e", "LLM_MODEL_PRICING_JSON"])
        command.extend([
            image_name,
            "python3", "/testbed/adver.py",
            "--data-path", "/testbed/adver_input.json",
            "--results-dir", "/results",
            "--bug-model", bug_model,
            "--judge-model", judge_model,
            "--filter-model-a", filter_model_a,
            "--filter-model-b", filter_model_b,
            "--attempts", str(attempts),
            "--suite-retries", str(suite_retries),
            "--test-agent", test_agent,
            "--test-agent-steps", str(test_agent_steps),
            "--test-agent-timeout", str(test_agent_timeout),
            "--start-index", str(entry_start_index),
            "--limit", str(entry_limit),
        ])
        if qwen_api_endpoint:
            command.extend(["--qwen-api-endpoint", qwen_api_endpoint])
        return command

    if workers == 1:
        print("运行 Java 测试（单容器串行）...")
        command = docker_command(data_path, test_results_dir, entry_start_index=start_index,
                                 entry_limit=limit)
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError("容器运行失败:\n"
                               f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        expected_outputs = [test_results_dir / "final_results.json",
                            test_results_dir / "filter_stats.json"]
        missing = [str(path) for path in expected_outputs if not path.is_file()]
        if missing:
            raise RuntimeError(f"容器成功退出但缺少输出文件: {missing}")
        print(result.stdout)
        return test_results_dir

    with data_path.open("r", encoding="utf-8") as f:
        entries = json.load(f)
    if not isinstance(entries, list):
        raise ValueError("输入 JSON 顶层必须是函数条目列表")
    if not entries:
        for name in ("final_results.json", "filter_stats.json"):
            (test_results_dir / name).write_text("[]\n", encoding="utf-8")
        return test_results_dir
    entries = entries[start_index:]
    if limit:
        entries = entries[:limit]

    run_root = Path(tempfile.mkdtemp(prefix=".parallel-adver-", dir=test_results_dir))
    print(f"并行运行 {len(entries)} 个函数，workers={workers}；临时结果: {run_root}")

    def run_one(index, entry):
        entry_dir = run_root / f"entry_{index:05d}"
        entry_dir.mkdir()
        entry_data_path = entry_dir / "input.json"
        entry_results_dir = entry_dir / "results"
        entry_results_dir.mkdir()
        with entry_data_path.open("w", encoding="utf-8") as f:
            json.dump([entry], f, ensure_ascii=False)
        result = subprocess.run(
            docker_command(entry_data_path, entry_results_dir), check=False,
            capture_output=True, text=True)
        stats_path = entry_results_dir / "filter_stats.json"
        final_path = entry_results_dir / "final_results.json"
        if result.returncode == 0 and stats_path.is_file() and final_path.is_file():
            with stats_path.open("r", encoding="utf-8") as f:
                stats = json.load(f)
            with final_path.open("r", encoding="utf-8") as f:
                finals = json.load(f)
            return index, finals, stats

        error = (result.stderr or result.stdout or "container exited without result files")[-4000:]
        failed_stat = {
            "name": entry.get("name", f"entry_{index}"),
            "status": "worker_error",
            "error": error,
        }
        return index, [], [failed_stat]

    completed = {}
    with ThreadPoolExecutor(max_workers=min(workers, len(entries))) as executor:
        futures = [executor.submit(run_one, index, entry)
                   for index, entry in enumerate(entries)]
        for future in as_completed(futures):
            index, finals, stats = future.result()
            completed[index] = (finals, stats)
            status = stats[0].get("status", "unknown") if stats else "missing_stats"
            print(f"并行任务 [{index + 1}/{len(entries)}] 完成: {status}")

    final_results = []
    filter_stats = []
    for index in range(len(entries)):
        finals, stats = completed[index]
        final_results.extend(finals)
        filter_stats.extend(stats)
    for path, value in ((test_results_dir / "final_results.json", final_results),
                        (test_results_dir / "filter_stats.json", filter_stats)):
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=4)
        temporary.replace(path)
    return test_results_dir


if __name__ == "__main__":
    parser = ArgumentParser(description="在 Docker 中运行 Java 错误代码构造流程")
    parser.add_argument(
        "--dockerfile",
        default=None,
        help=("可选。未指定时自动查找 "
              "dockerfiles/<repo-dir 末级目录>/.../Dockerfile"))
    parser.add_argument("--repo-dir", default="projects/flink",
                        help="用于推导镜像名和结果目录的项目路径")
    parser.add_argument("--data-file", default="tem/flink_10.json")
    parser.add_argument("--bug-model", default="gpt-5-nano")
    parser.add_argument("--judge-model", default="gpt-5-nano")
    parser.add_argument("--filter-model-a", default="gpt-5-nano")
    parser.add_argument("--filter-model-b", default="qwen3.5-flash")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--suite-retries", type=int, default=1,
                        choices=(1,),
                        help="固定为 1：初始测试失败后重写一次，合计两套测试")
    parser.add_argument("--qwen-api-endpoint", default=None,
                        help="Qwen 过滤模型的 OpenAI-compatible endpoint")
    parser.add_argument("--test-agent", choices=("mini-swe", "restricted"), default="mini-swe",
                        help="mini-swe 为连续 Bash 测试智能体；restricted 为旧受限搜索模式")
    parser.add_argument("--test-agent-steps", type=int, default=100)
    parser.add_argument("--test-agent-timeout", type=int, default=1200)
    parser.add_argument("--start-index", type=int, default=0,
                        help="从输入数据的指定零基索引开始处理")
    parser.add_argument("--limit", type=int, default=0,
                        help="最多处理的函数数；0 表示处理到末尾")
    parser.add_argument("--workers", type=int, default=1,
                        help="独立 Docker 函数任务的最大并发数；1 为原串行模式")
    parser.add_argument(
        "--config-file", action="append", nargs=2, default=[],
        metavar=("HOST_FILE", "PROJECT_PATH"),
        help="复用生成测试时修改的配置文件，并只读挂载到容器内的项目相对路径；可重复")
    cli_args = parser.parse_args()
    output_dir = create_and_run_java(
        cli_args.dockerfile, cli_args.repo_dir, cli_args.data_file,
        bug_model=cli_args.bug_model,
        judge_model=cli_args.judge_model,
        filter_model_a=cli_args.filter_model_a,
        filter_model_b=cli_args.filter_model_b,
        attempts=cli_args.attempts,
        suite_retries=cli_args.suite_retries,
        qwen_api_endpoint=cli_args.qwen_api_endpoint,
        test_agent=cli_args.test_agent,
        test_agent_steps=cli_args.test_agent_steps,
        test_agent_timeout=cli_args.test_agent_timeout,
        start_index=cli_args.start_index,
        limit=cli_args.limit,
        workers=cli_args.workers,
        config_files=cli_args.config_file)
    print(f"完成，结果保存在: {output_dir}")
