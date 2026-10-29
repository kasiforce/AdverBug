import json
import os
from pathlib import Path
from bug_generation_agent import BugGenerationAgent
from test_gen import TestGenerationAgent
from llm_config import LLMConfig
from valid_agent import ValidAgent

def delete_test_files_in_test_dirs(project_root):
    """在 test/tests 目录中删除 *test*.java 文件"""
    # 查找 test/tests 目录
    test_dirs = []
    for root, dirs, files in os.walk(project_root):
        root_path = Path(root)

        # 跳过某些目录
        skip_dirs = ['.git', 'venv', '.venv', '__pycache__']
        if any(skip in root_path.parts for skip in skip_dirs):
            continue

        # 如果是 test 或 tests 目录
        if root_path.name.lower() in ['test', 'tests']:
            test_dirs.append(root_path)

    if not test_dirs:
        print("未找到 test 或 tests 目录")
        return

    # 查找并删除测试文件
    deleted_files = []
    for test_dir in test_dirs:
        for file in test_dir.rglob('*.java'):
            if 'Test' in file.name:
                try:
                    os.remove(file)
                    deleted_files.append(file)
                except Exception as e:
                    print(f"删除失败 {file}: {e}")

    # 显示结果
    print(f"在 {len(test_dirs)} 个测试目录中删除了 {len(deleted_files)} 个测试文件:")
    for file in deleted_files[:10]:
        print(f"  {file}")

    if len(deleted_files) > 10:
        print(f"  ... 还有 {len(deleted_files)-10} 个文件")


def main(data_path):
    llm_config = LLMConfig(
        api_endpoint=os.getenv("LLM_API_ENDPOINT", "https://api.agicto.cn/v1"),
        model_name=os.getenv("LLM_MODEL_NAME", "gpt-5.4-mini"),
    )
    bug_agent = BugGenerationAgent(llm_config)
    test_agent = TestGenerationAgent(llm_config)
    valid_agent = ValidAgent(llm_config)
    final_results = []
    with open(data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    for entry in data:
        code = entry.get("code", "")
        src_file = entry.get("src_file", "")
        test_file = entry.get("test_file", "")
        bug_code = ""
        test_info = ""
        flag = "src_test_fail"
        bug_code_list = []
        test_code_list = []
        for i in range(5):
            if i == 0:
                bug_json = bug_agent.init_bug_prompt(code)
                bug_code = bug_json.get("buggy_code", "")
            else:
                bug_json = bug_agent.enhance_bug_prompt(code, bug_code, test_info)
                bug_code = bug_json.get("buggy_code", "")

            with open(src_file, 'r', encoding='utf-8') as f:
                src = f.read()
            # for item in bug_json:
            #     bug_code = item.get("buggy_code", "")
            if code in src:
                src = src.replace(code, bug_code)
                with open(src_file, 'w', encoding='utf-8') as f:
                    f.write(src)
                print(f"已将源代码替换为错误代码")

            result = subprocess.run(
                ["mvn", "compile", "-Drat.skip=true", "--show-version", "--batch-mode", "--no-transfer-progress", "-q"],
                cwd="/testbed",
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                error_message = result.stdout
                f = False
                for i in range(3):
                    bug_code_fix = bug_agent.fix_bug_prompt(bug_code, error_message)
                    src = src.replace(bug_code, bug_code_fix)
                    with open(src_file, 'w', encoding='utf-8') as f:
                        f.write(src)

                    result = subprocess.run(
                        ["mvn", "compile", "-Drat.skip=true", "-q"],
                        cwd="/testbed",
                        capture_output=True,
                        text=True
                    )
                    if result.returncode == 0:
                        bug_code = bug_code_fix
                        print(f"已将错误代码修复")
                        f = True
                        break
                    else:
                        error_message = result.stdout
                        bug_code = bug_code_fix
                        print(f"修复尝试 {i+1} 失败，错误信息:\n{error_message}")

                if not f:
                    with open(src_file, 'r', encoding='utf-8') as f:
                        src = f.read()
                    src = src.replace(bug_code, code)
                    with open(src_file, 'w', encoding='utf-8') as f:
                        f.write(src)
                    continue


            
            bug_code_list.append(bug_code)

            # delete_test_files_in_test_dirs("/testbed")
            
            tests = test_agent.init_test_prompt(bug_code, entry)
            print(tests)
            test_file = entry.get("test_file", "")
            os.makedirs(os.path.dirname(test_file), exist_ok=True)
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write(tests)

            result = subprocess.run(
                ["mvn", "test-compile", "-Drat.skip=true", "--show-version", "--batch-mode", "--no-transfer-progress", "-q"],
                cwd="/testbed",
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                error_message = result.stdout
                for i in range(5):
                    test_code_fix = test_agent.fix_test_prompt(tests, error_message)
                    with open(test_file, 'w', encoding='utf-8') as f:
                        f.write(test_code_fix)

                    result = subprocess.run(
                        ["mvn", "test-compile", "-Drat.skip=true", "--show-version", "--batch-mode", "--no-transfer-progress", "-q"],
                        cwd="/testbed",
                        capture_output=True,
                        text=True
                    )
                    if result.returncode == 0:
                        tests = test_code_fix
                        print(f"已将错误测试代码修复")
                        break
                    else:
                        error_message = result.stdout
                        tests = test_code_fix
                        print(f"测试修复尝试 {i+1} 失败，错误信息:\n{error_message}")

                # result = subprocess.run(
                #     ["mvn", "verify", "-Drat.skip=true", "-DforkCount=0", "-q"],
                #     cwd="/testbed",
                #     capture_output=True,
                #     text=True
                # )
                test_class = os.path.splitext(os.path.basename(test_file))[0]

                result = subprocess.run(
                    [
                        "mvn",
                        "test",
                        f"-Dtest={test_class}",
                        "-Drat.skip=true",
                        "-DforkCount=0",
                        "-Dspotless.check.skip=true",
                        "--show-version",
                        "--batch-mode",
                        "--no-transfer-progress",
                        "-q"
                    ],
                    cwd="/testbed",
                    capture_output=True,
                    text=True
                )
                
                test_code_list.append(tests)

                print(result.stdout)
                if result.returncode != 0:
                    with open(src_file, 'r', encoding='utf-8') as f:
                        src = f.read()
                    src = src.replace(bug_code, code)
                    with open(src_file, 'w', encoding='utf-8') as f:
                        f.write(src)
                    os.remove(test_file)
                    print("生成的测试失败，详细信息：\n", result.stdout[-1000:])
                    # output = result.stdout.split("ERROR]")[0].strip()
                    # output1 = output.split(output)[0].strip()
                    test_info = tests + "\n" + result.stdout  # Get the last 1000 characters of stdout  
                    continue
                else:
                    print("生成的测试通过")
                    flag = "generated_test_pass"
                    break
                    tests = test_agent.enhance_test_prompt(bug_code, entry, tests)
                    with open(test_file, 'w', encoding='utf-8') as f:
                        f.write(tests)
                    result = subprocess.run(
                        ["mvn", "test-compile", "-Drat.skip=true", "-q"],
                        cwd="/testbed",
                        capture_output=True,
                        text=True
                    )
                    if result.returncode != 0:
                        error_message = result.stdout
                        for i in range(5):
                            test_code_fix = test_agent.fix_test_prompt(tests, error_message)
                            with open(test_file, 'w', encoding='utf-8') as f:
                                f.write(test_code_fix)

                            result = subprocess.run(
                                ["mvn", "test-compile", "-Drat.skip=true", "-q"],
                                cwd="/testbed",
                                capture_output=True,
                                text=True
                            )
                            if result.returncode == 0:
                                tests = test_code_fix
                                print(f"已将错误测试代码修复")
                                break
                            else:
                                error_message = result.stdout
                                tests = test_code_fix
                                print(f"测试修复尝试 {i+1} 失败，错误信息:\n{error_message}")

                    test_code_list.append(tests)
                    
                    result = subprocess.run(
                        ["mvn", "verify", "-Drat.skip=true", "-DforkCount=0", "-q"],
                        cwd="/testbed",
                        capture_output=True,
                        text=True
                    )
                    if result.returncode != 0:
                        with open(src_file, 'r', encoding='utf-8') as f:
                            src = f.read()
                        src = src.replace(bug_code, code)
                        with open(src_file, 'w', encoding='utf-8') as f:
                            f.write(src)
                        os.remove(test_file)
                        print("增强的测试失败，详细信息：\n", result.stdout[-1000:])
                        # output = result.stdout.split("ERROR]")[0].strip()
                        # output1 = output.split(output)[0].strip()
                        test_info = tests + "\n" + result.stdout  # Get the last 1000 characters of stdout
                        continue
                    else:
                        print("增强的测试通过")
                        flag = "enhanced_test_pass"
                        break
        
        with open(src_file, 'r', encoding='utf-8') as f:
            src = f.read()
        src = src.replace(bug_code, code)
        with open(src_file, 'w', encoding='utf-8') as f:
            f.write(src)
        if test_file and os.path.exists(test_file):
            os.remove(test_file)     

        validation_result = valid_agent.validate(code, bug_code_list[-1], test_code_list[-1] if test_code_list else "")
        final_flag = validation_result.get("is_valid_bug", False)
        if final_flag:
            entry["buggy_code"] = bug_code_list
            entry["tests"] = test_code_list
            # entry["bug_info"] = bug_json
            entry["flag"] = flag
            
            final_results.append(entry)
            with open("/testbed/final_results.json", 'w', encoding='utf-8') as f:
                json.dump(final_results, f, ensure_ascii=False, indent=4)

            subprocess.run(
                ["cp", "/testbed/final_results.json", "/testbed/results/"],
                cwd="/testbed",
                capture_output=True,
                text=True
            )
            print(f"最终生成的错误代码:\n{bug_code}")

    

if __name__ == "__main__":
    import argparse
    import subprocess

    parser = argparse.ArgumentParser(description="Generate bugs and tests for Java code.")
    parser.add_argument("--data-path", type=str, required=True, help="Path to the JSON data file.")
    args = parser.parse_args()

    main(args.data_path)
                
        
        

        
