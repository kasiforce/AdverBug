import subprocess
import os
import sys
import json
import xml.etree.ElementTree as ET
from argparse import ArgumentParser

import csv
import xml.etree.ElementTree as ET

from pathlib import Path
import javalang
from collections import defaultdict
from jacoco_xml import parse_jacoco_xml


def syntax_analyse(data_file):
    with open(data_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    total = 0
    syntax_correct = 0
    # data = data["items"]
    for item in data:
        # test_code = item.get("generated_tests", "")
        test_code = item["generated_tests"][0] if item.get("generated_tests") else ""
        # for test in test_code:
        if not test_code.strip():
            continue

        total += 1
        try:
            javalang.parse.parse(test_code)
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


def create_and_run_java(dockerfile_path, repo_dir, data_file, pom):
    cwd = os.getcwd()
    print(f"当前工作目录: {cwd}")

    # 1. 准备目录
    repo_name = repo_dir
    if "/" in repo_dir:
        repo_name = repo_dir.split("/")[1]
    test_results_dir = os.path.join(cwd, "test_results", "java", repo_name, "src_src_junit5_copilot_gpt-5.6-luna")

    os.makedirs(test_results_dir, exist_ok=True)

    syntax_report = syntax_analyse(data_file)

    project_dir = os.path.join(cwd, repo_dir)


    # 2. 构建镜像
    print("开始构建 Java 项目镜像...")
    try:
        subprocess.run([
            "docker", "build",
            "-t", f"java-repo-{repo_name}",
            "-f", dockerfile_path,
            "."
        ], check=True)
    except subprocess.CalledProcessError as e:
        print(f"镜像构建失败: {e}")
        sys.exit(1)

    # 3. 运行测试
    # 注意：这里假设项目使用 Maven。如果是 Gradle，请将 mvn 命令改为 ./gradlew
    print("运行 Java 测试 (Maven + JaCoCo)...")
    try:


        result = subprocess.run([
            "docker", "run", "--rm",
            "-v", f"{test_results_dir}:/results",
            "-v", "./gen_test/gen_tests_files.py:/testbed/gentests_files.py",
            "-v", "./delete_files.py:/testbed/delete_files.py",
            "-v", f"./{data_file}:/testbed/{data_file}",
            "-v", f"./{pom}:/testbed/pom.xml",
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

                echo "生成测试文件..."
                python3 /testbed/gentests_files.py \
                    --project-root /testbed \
                    --data-path /testbed/{data_file}

                  
                MAX_RETRIES=10
                RETRY_COUNT=0
                LOG_FILE="/tmp/compile.log"
                CLEAN_LOG="/tmp/compile.clean.log"

                while true; do
                    echo "===== 编译尝试 $((RETRY_COUNT+1)) ====="
                    # 运行编译，输出到日志文件，并保存退出码
                    # ./mvnw -B spotless:apply
                    ./mvnw test-compile -Drat.skip=true -Dcheckstyle.skip=true -Dspotless.check.skip=true  > "$LOG_FILE" 2>&1
                    MVN_EXIT_CODE=$?
                    # 去除 ANSI 颜色码，生成干净日志（不影响后续判断）
                    sed -e 's/\x1b\[[0-9;]*m//g' "$LOG_FILE" > "$CLEAN_LOG"

                    if [ $MVN_EXIT_CODE -eq 0 ]; then
                        echo "✅ 编译成功！"
                        break
                    else
                        echo "❌ 编译失败，正在删除错误文件..."
                        python3 /testbed/delete_files.py "$CLEAN_LOG"

                        RETRY_COUNT=$((RETRY_COUNT+1))
                        if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
                            echo "已达到最大重试次数 ($MAX_RETRIES)，退出。"
                            exit 1
                        fi
                        sleep 2
                    fi
                done

                
                
                # mvn clean test -Dtest='*Test,*Tests' -DskipTests=false -Dmaven.test.skip=false -DfailIfNoTests=false -Dmaven.test.failure.ignore=true -Drat.skip=true -Dsurefire.failIfNoSpecifiedTests=false -B jacoco:report
                # 读取生成的测试类名列表，转成逗号分隔
                TEST_CLASSES=$(tr '\n' ',' < /results/generated_test_classes.txt 2>/dev/null | sed 's/,$//')
                if [ -z "$TEST_CLASSES" ]; then
                    echo "没有生成任何测试类，跳过测试运行。"
                    exit 0
                fi
                echo "只运行模型生成的测试类：$TEST_CLASSES"

                ./mvnw clean \
                    org.jacoco:jacoco-maven-plugin:0.8.12:prepare-agent \
                    test \
                    org.jacoco:jacoco-maven-plugin:0.8.12:report \
                    -Dtest="$TEST_CLASSES" \
                    -Dmaven.test.failure.ignore=true \
                    -Drat.skip=true \
                    -Dcheckstyle.skip=true \
                    -Dspotless.check.skip=true \
                    -Dsurefire.failIfNoSpecifiedTests=false \
                    -B

                # 统计编译成功的测试类，并输出文件列表
                compiled_class_files=$(find . -path "*/target/test-classes/*Tests.class" ! -name "*\\$*")
                compiled_count=$(echo "$compiled_class_files" | wc -l)
                echo "$compiled_count" > /results/compiled_tests_count.txt
                echo "$compiled_class_files" > /results/compiled_tests_list.txt   # 保存文件列表

                    # 4. 创建报告目录
                mkdir -p /results/reports

                # 5. 收集 JUnit XML 报告（所有子模块的 surefire 报告）
                echo "开始搜集 JUnit XML 报告..."
                find . -name "TEST-*.xml" -path "*/target/surefire-reports/*" -exec cp {{}} /results/reports/ \;

                # 6. 收集 JaCoCo CSV 和 XML 报告（便于后续解析）
                echo "开始搜集 JaCoCo 报告..."
                find . -name "jacoco.csv" -path "*/target/site/jacoco/*" | while read -r csv_file; do
                    # 生成相对路径前缀（将 / 替换为 _）以避免重名
                    rel_path=$(realpath --relative-to="$ROOT_DIR" "$(dirname "$csv_file")/../.." | tr '/' '_')
                    if [ -z "$rel_path" ] || [ "$rel_path" = "." ]; then
                        prefix="root"
                    else
                        prefix="$rel_path"
                    fi
                    cp "$csv_file" "/results/${{prefix}}_jacoco.csv"
                    echo "已拷贝 CSV: ${{prefix}}_jacoco.csv"
                done

                # 7. 收集 jacoco.xml（包含详细的方法级行覆盖率）
                find . -name "jacoco.xml" -path "*/target/site/jacoco/*" | while read -r xml_file; do
                    rel_path=$(realpath --relative-to="$ROOT_DIR" "$(dirname "$xml_file")/../.." | tr '/' '_')
                    if [ -z "$rel_path" ] || [ "$rel_path" = "." ]; then
                        prefix="root"
                    else
                        prefix="$rel_path"
                    fi
                    cp "$xml_file" "/results/${{prefix}}_jacoco.xml"
                    echo "已拷贝 XML: ${{prefix}}_jacoco.xml"
                done

                # 8. 列出结果目录内容（调试）
                echo "搜集完成。/results 目录内容："
                ls -R /results
       
            """
        ], check=False, capture_output=True, text=True)
        # 打印输出
        print("=== STDOUT ===")
        print(result.stdout)
        

        # 4. 解析结果
        compiled_count = get_compiled_tests_count(test_results_dir)
        junit_results = calculate_test_pass_rate(os.path.join(test_results_dir, "reports"))
        coverage_results = parse_jacoco_xml(os.path.join(test_results_dir, "target_jacoco.xml"), data_file)

        summary = syntax_report | {
            "compile_pass": compiled_count,
            "test_summary": junit_results
        }

        summary = summary | coverage_results

        # summary = {
        #     "compile_pass": compiled_count,
        #     "test_summary": junit_results,
        #     "coverage_summary": coverage_results
        # }

        with open(os.path.join(test_results_dir, "summary.json"), 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        print(f"测试完成，报告已生成: {test_results_dir}/summary.json")

    except subprocess.CalledProcessError as e:
        print(f"测试运行失败!")
        print(f"错误标准输出 (stdout): \n{e.stdout}")
        print(f"错误标准错误 (stderr): \n{e.stderr}")
        # 即使失败也尝试生成部分报告
        sys.exit(1)


if __name__ == "__main__":
    # 示例调用
    create_and_run_java("dockerfiles/flink/Dockerfile", "projects/flink", "test_results/java/flink/junit5_agent/copilot_testgen_results.json", "dockerfiles/flink/pom.xml")
    # pass