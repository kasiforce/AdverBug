# !/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import os
import sys
import json
from pathlib import Path
from argparse import ArgumentParser
# from cal_jest_cov import parse_coverage


def syntax_analyse_js(project_root, gen_tests_dir):
    """
    对生成的 JS 测试文件做语法检查（使用 node --check）。
    有语法错误的测试文件会被删除。
    返回：{total, syntax_correct, syntax_correct_rate}
    """
    test_dir = os.path.join(project_root, gen_tests_dir)
    p = Path(test_dir)
    if not p.exists():
        print(f"测试目录不存在: {test_dir}")
        return {"total": 0, "syntax_correct": 0, "syntax_correct_rate": 0}

    total = 0
    syntax_correct = 0
    for js_file in p.rglob("*.js"):
        name_low = js_file.name.lower()
        # 仅处理看起来像测试的文件（包含 test）
        if "test" in name_low or name_low.startswith("spec") or name_low.endswith(".spec.js"):
            total += 1
            try:
                # node --check filename 仅做语法校验（Node 10+ 支持）
                res = subprocess.run(["node", "--check", str(js_file)], capture_output=True, text=True)
                if res.returncode == 0:
                    syntax_correct += 1
                else:
                    print(f"[语法错误] 删除文件 {js_file}:\n{res.stderr.strip()}")
                    try:
                        js_file.unlink()
                    except Exception as e:
                        print(f"删除失败: {e}")
            except FileNotFoundError:
                # 本地没有 node，可选择不做本地检查或用其它方式
                print("本地未找到 node，可跳过本地语法检查（Docker 内仍会检查）。")
                # 认为语法未知，保留文件
                syntax_correct += 1

    rate = (syntax_correct / total) if total > 0 else 0
    return {"total": total, "syntax_correct": syntax_correct, "syntax_correct_rate": rate}


def calculate_test_metrics_js(report_file):
    """
    解析 Jest JSON 报告（npx jest --json --outputFile=...）。
    返回：compile (suites passed count)，testcase dict 包含传递率等
    """
    if not os.path.exists(report_file):
        print(f"未找到测试报告: {report_file}")
        return {"compile_pass": 0}, {"testcase": {}}

    with open(report_file, 'r', encoding='utf-8') as f:
        report = json.load(f)

    # Jest JSON output fields: numTotalTests, numPassedTests, numFailedTests, numTotalTestSuites, testResults(list)
    test_results = report.get("testResults", [])

    # 安全地计算测试套件统计
    total_suites = len(test_results)
    passed_suites = sum(1 for s in test_results if isinstance(s, dict) and s.get("status") == "passed")

    # 修复：安全地计算 total_tests
    # 首先检查 report 中是否有 numTotalTests
    total_tests = report.get("numTotalTests", 0)

    # 如果没有 numTotalTests，则从 testResults 中计算
    if total_tests == 0 and test_results:
        total_tests = 0
        for suite in test_results:
            if isinstance(suite, dict):
                assertion_results = suite.get("assertionResults", [])
                if isinstance(assertion_results, list):
                    total_tests += len(assertion_results)

    # 安全地计算 passed_tests
    passed_tests = report.get("numPassedTests", 0)
    if passed_tests == 0 and test_results:
        passed_tests = 0
        for suite in test_results:
            if isinstance(suite, dict):
                assertion_results = suite.get("assertionResults", [])
                if isinstance(assertion_results, list):
                    passed_tests += len(
                        [a for a in assertion_results if isinstance(a, dict) and a.get("status") == "passed"])

    # 安全地计算 failed_tests
    failed_tests = report.get("numFailedTests", 0)
    if failed_tests == 0 and test_results:
        failed_tests = 0
        for suite in test_results:
            if isinstance(suite, dict):
                assertion_results = suite.get("assertionResults", [])
                if isinstance(assertion_results, list):
                    failed_tests += len(
                        [a for a in assertion_results if isinstance(a, dict) and a.get("status") == "failed"])

    # 安全地计算 skipped_tests
    skipped_tests = report.get("numPendingTests", 0)
    if skipped_tests == 0 and test_results:
        skipped_tests = 0
        for suite in test_results:
            if isinstance(suite, dict):
                assertion_results = suite.get("assertionResults", [])
                if isinstance(assertion_results, list):
                    skipped_tests += len([a for a in assertion_results if
                                          isinstance(a, dict) and a.get("status") in ("pending", "skipped")])

    # 如果 total_tests 仍然为 0，尝试使用其他方法计算
    if total_tests == 0:
        total_tests = passed_tests + failed_tests + skipped_tests

    # 创建测试用例摘要
    testcase_summary = {
        "total": total_tests,
        "passed": passed_tests,
        "failed": failed_tests,
        "skipped": skipped_tests,
    }

    # 计算率，保护除零
    test_pass_rate = (passed_tests / total_tests) if total_tests > 0 else 0

    # 修复：确保 run_pass_rate 计算安全
    runtime_errors = report.get("numRuntimeErrorTestSuites", 0)
    if total_tests > 0:
        run_pass_rate = ((total_tests - runtime_errors - failed_tests) / total_tests)
    else:
        run_pass_rate = 0

    testcase_summary.update({
        "test_pass_rate": test_pass_rate,
        "run_pass_rate": run_pass_rate,
        "num_total_suites": total_suites,
        "num_passed_suites": passed_suites,
        "num_reported_test_suites": report.get("numTotalTestSuites", total_suites)
    })

    compile = {
        "compile_pass": passed_suites,
        "compile_total": total_suites,
        # compile_pass_rate 在汇总处计算（可以基于 syntax_analyse 的 total）
    }

    return compile, {"testcase": testcase_summary}


def get_coverage_rate_js(coverage_summary_file):
    """
    解析 Istanbul/nyc 生成的 coverage-summary.json（位于 coverage/coverage-summary.json）。
    返回类似你原来 get_coverage_rate 的结构。
    """
    if not os.path.exists(coverage_summary_file):
        print(f"未找到 coverage summary: {coverage_summary_file}")
        return {
            "total_line_coverage": 0,
            "total_branch_coverage": 0,
            "total_function_coverage": 0,
            "total_statement_coverage": 0,
            "file_coverage": {},
            "summary": {}
        }

    with open(coverage_summary_file, 'r', encoding='utf-8') as f:
        coverage = json.load(f)

    # coverage-summary.json 的结构通常包含 "total" 字段以及每个文件的 coverage object
    totals = coverage.get("total", {})
    result = {
        "total_line_coverage": totals.get("lines", {}).get("pct", 0),
        "total_branch_coverage": totals.get("branches", {}).get("pct", 0),
        "total_function_coverage": totals.get("functions", {}).get("pct", 0),
        "total_statement_coverage": totals.get("statements", {}).get("pct", 0),
        "file_coverage": {},
        "summary": {
            "lines": totals.get("lines", {}),
            "branches": totals.get("branches", {}),
            "functions": totals.get("functions", {}),
            "statements": totals.get("statements", {})
        }
    }

    # 逐文件记录
    for file_path, data in coverage.items():
        if file_path == "total":
            continue
        # 每个文件数据示例： { "lines": {"total": X, "covered": Y, "skipped": 0, "pct": Z}, ... }
        file_entry = {
            "line_coverage": data.get("lines", {}).get("pct", 0),
            "branch_coverage": data.get("branches", {}).get("pct", 0),
            "function_coverage": data.get("functions", {}).get("pct", 0),
            "statement_coverage": data.get("statements", {}).get("pct", 0),
            "lines": data.get("lines", {}),
            "branches": data.get("branches", {}),
            "functions": data.get("functions", {}),
            "statements": data.get("statements", {})
        }
        result["file_coverage"][file_path] = file_entry

    return result


def create_and_run_java(dockerfile_path, project_root, data_file, github_token=None):
    """
    主要流程：
      1) 本地做语法检查并删除有语法错误的测试文件
      2) 用 Docker 构建镜像并运行测试（在容器内使用 npm / npx jest）
      3) 解析 /results/report.json 与 /results/coverage/coverage-summary.json，生成 summary.json
    注意：Dockerfile 应包含 Node 环境，能执行 npm / npx / node。
    """
    cwd = os.getcwd()
    print(f"当前工作目录: {cwd}")

    if not os.getenv("COPILOT_PROVIDER_API_KEY"):
        raise RuntimeError("COPILOT_PROVIDER_API_KEY must be set")

    # 先做本地语法检测（可选）
    project_dir = os.path.join(cwd, project_root)
    # syntax_report = syntax_analyse_js(project_dir, gen_tests_dir)

    # 准备测试结果目录（主机）
    test_results_base = os.path.join(cwd, "test_results", "java")
    repo_name = project_root
    if "/" in project_root:
        repo_name = project_root.split("/")[1]
    test_results_dir = os.path.join(test_results_base, repo_name, "junit5_agent")
    os.makedirs(test_results_dir, exist_ok=True)

    # 构建镜像
    print("开始构建镜像...")
    try:
        subprocess.run([
            "docker", "build",
            "-t", f"java-repo-{repo_name}",
            "-f", dockerfile_path,
            "."
        ], check=True, cwd=cwd)
    except subprocess.CalledProcessError as e:
        print(f"镜像构建失败: {e}")
        sys.exit(1)

    print("镜像构建成功，开始运行测试容器...")

    # 在容器中运行：安装依赖并执行 jest（生成 JSON 报告与 coverage）
    # 注意：假设项目根目录包含 package.json 并声明 jest 配置，或者使用 npx jest 命令
    try:
        # 构造要在容器中执行的脚本（多行 bash）
        result = subprocess.run([
            "docker", "run", "--rm",
            "-e", "COPILOT_PROVIDER_API_KEY",
            "-e", f"COPILOT_PROVIDER_BASE_URL={os.getenv('COPILOT_PROVIDER_BASE_URL', 'https://api.agicto.cn/v1')}",
            "-e", f"COPILOT_MODEL={os.getenv('COPILOT_MODEL', 'gpt-5.6-luna')}",
            "-v", f"{test_results_dir}:/results",
            "-v", "./agent/agent.py:/testbed/agent.py",
            # "-v", "./gen_test/gen_tests_files.py:/testbed/delete.py",
            "-v", f"./{data_file}:/testbed/{data_file}",
            # "-v", f"{os.path.expanduser('~/.m2')}:/root/.m2",
            f"java-repo-{repo_name}",
            "bash", "-c", f"""
                # set -e
                cd /testbed
                ROOT_DIR="$(pwd)"
                # 安装 Python3
                if ! command -v python3 &> /dev/null; then
                    apt-get update && apt-get install -y python3
                fi

                

                # 使用 ci 更可重复；若没有 package-lock.json 可改成 npm install
                apt-get update
                apt-get install -y curl ca-certificates
                curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
                apt-get install -y nodejs

                npm install -g @github/copilot
                # 1. 注册 .NET 技能市场
                copilot plugin marketplace add dotnet/skills

                # 2. 从市场中安装你需要的插件，比如 dotnet-test
                copilot plugin install dotnet-test@dotnet-agent-skills

                # export COPILOT_GITHUB_TOKEN="$GITHUB_TOKEN"

                # python3 /testbed/delete.py --project-root /testbed --data-path /testbed/{data_file}

                python3 /testbed/agent.py \
                    --dataset /testbed/{data_file}
                    
                
       
            """
        ], check=False, capture_output=True, text=True)


    except subprocess.CalledProcessError as e:
        print(f"容器运行/测试失败: {e}")
        # 仍然尝试解析已有报告
        # sys.exit(1)

    


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--dockerfile-path", type=str, default="Dockerfile", help="Dockerfile 路径")
    parser.add_argument("--project-root", type=str, default=".", help="项目根目录（本地）")
    parser.add_argument("--data-file", type=str, help="数据文件路径")
    # parser.add_argument("--github-token", type=str, help="GitHub Token")
    args = parser.parse_args()

    # 示例调用：你可以改成你项目的路径
    create_and_run_java("dockerfiles/flink/Dockerfile",
                      project_root="projects/flink", data_file="flink_specification.json", github_token="")
    # create_and_run_js(args.dockerfile_path, args.test_dir, args.cover_source, args.project_root)
