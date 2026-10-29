import re
import os
from pathlib import Path
import json
import subprocess
import sys
# import argparse
from argparse import ArgumentParser
from typing import List, Dict, Tuple


TEST_DIRECTORY_NAMES = {
    "test", "tests", "__test__", "__tests__", "spec", "specs",
    "androidtest", "testfixtures",
}
SKIP_DIRECTORY_NAMES = {".git", "venv", ".venv", "__pycache__"}
TEST_SOURCE_SUFFIXES = {
    "java": {".java", ".scala", ".kt", ".groovy"},
    "python": {".py"},
}


def _contains_adjacent_parts(path, first, second):
    parts = [part.lower() for part in path.parts]
    return any(parts[index:index + 2] == [first, second] for index in range(len(parts) - 1))


def delete_test_files_in_test_dirs(project_root, language="java"):
    """按通用测试目录删除 Java 或 Python 测试源码，返回已删除路径。"""
    language = language.lower()
    if language not in TEST_SOURCE_SUFFIXES:
        raise ValueError(f"不支持的语言: {language}")

    project_root = Path(project_root)
    deleted_files = []
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [directory for directory in dirs if directory not in SKIP_DIRECTORY_NAMES]
        root_path = Path(root)
        relative_root = root_path.relative_to(project_root)
        relative_parts = {part.lower() for part in relative_root.parts}
        if not relative_parts.intersection(TEST_DIRECTORY_NAMES):
            continue
        if language == "java" and _contains_adjacent_parts(relative_root, "src", "main"):
            continue

        for filename in files:
            file_path = root_path / filename
            if file_path.suffix not in TEST_SOURCE_SUFFIXES[language]:
                continue
            if language == "python" and filename.lower() == "conftest.py":
                continue
            try:
                file_path.unlink()
                deleted_files.append(file_path)
            except OSError as error:
                print(f"删除失败 {file_path}: {error}")

    print(f"共删除 {len(deleted_files)} 个 {language} 测试源码文件")
    for file_path in deleted_files[:10]:
        print(f"  {file_path}")
    if len(deleted_files) > 10:
        print(f"  ... 还有 {len(deleted_files) - 10} 个文件")
    return deleted_files
# def write_generated_tests(project_root, test_json_path, bug_json_path=None):
#     """生成测试文件（指定 utf-8 编码）"""
#     try:
#         with open(test_json_path, 'r', encoding='utf-8') as f:
#             functions = json.load(f)
#             print(len(functions))
#         # with open(bug_json_path, 'r', encoding='utf-8') as f:
#         #     bugs = json.load(f)
#         #     # print(len(bugs))
#         # bug_code = bugs[1]["bugged_code"]
#         # src_code = bugs[1]["src_code"]
#         # functions = [functions[0]]
#         # functions = functions["items"]
#         for func in functions:
#             # print(func)
#             test_file = func.get("test_file", "")
#             root = func.get("project_root", "").split('/')
#             # print(root)
#             # if len(root) > 2 and root[-1] != 'src':
#             #     test_file = os.path.join(root[-1], test_file)
#             # test_file1 = project_root + "/" + test_file
#             test_file1 = test_file
#             dir_path = os.path.dirname(test_file1)
#             if not os.path.exists(dir_path):
#                 os.makedirs(dir_path, exist_ok=True)

#             # test = func["repair_history"][-1]["test_code"]
#             # raw_code = test
#             raw_code = "\n\n".join(func["generated_tests"])
#             raw_code = raw_code.strip()
#             # if func["tests"]:
#             #     raw_code = func["tests"][-1]


            
#             # raw_code = func.get("generated_tests", "")
#             # if func["tests"]:
#             #     raw_code = func["tests"][-1]

#             # 写入文件（UTF-8）
#             if raw_code:
#                 with open(test_file1, 'w', encoding='utf-8') as f:
#                     f.write("\n\n" + raw_code)
#                 print(f"写入 {test_file1}")

#             # if func.get("code", "") == src_code:
#                 # print(f"找到匹配的源代码")
#             # bug_code = func["buggy_code"][-1]
#             # src_code = func.get("code", "")
#             # src_file = func.get("src_file", "")
#             # with open(src_file, 'r', encoding='utf-8') as f:
#             #     src_content = f.read()
#             # if bug_code and src_code in src_content:
#             #     src_content = src_content.replace(src_code, bug_code)
#             #     # print(f"替换的源代码: {src_content}")
#             #     print(f"替换 {src_file} 中的源代码为 buggy_code")
#             #     with open(src_file, 'w', encoding='utf-8') as f:
#             #         f.write(src_content)


#     except Exception as e:
#         print(f"写入文件失败: {e}")


def write_generated_tests(project_root, test_json_path, bug_json_path=None):
    generated_classes = []
    with open(test_json_path, 'r', encoding='utf-8') as f:
        functions = json.load(f)
    functions = [functions[0]]
    for func in functions:
        test_file = func.get("test_file", "")
        if not test_file:
            continue
        dir_path = os.path.dirname(test_file)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)

        raw_code = "\n\n".join(func["generated_tests"]).strip()
        if not raw_code:
            continue

        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("\n\n" + raw_code)
        print(f"写入 {test_file}")

        # 收集类名（文件名去掉 .java）
        cls = os.path.splitext(os.path.basename(test_file))[0]
        generated_classes.append(cls)

    # 输出白名单，供 bash 使用
    os.makedirs("/results", exist_ok=True)
    with open("/results/generated_test_classes.txt", 'w') as f:
        f.write("\n".join(generated_classes) + "\n")
    print(f"共生成 {len(generated_classes)} 个测试类")



if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "--project-root",
        type=str,
        help="The root dir of project.",
    )
    parser.add_argument(
        "--data-path",
        type=str,
        help="Path to data.",
    )
    parser.add_argument(
        "--language",
        choices=("java", "python"),
        default="java",
        help="Language whose test sources should be removed.",
    )
    parser.add_argument(
        "--delete-tests",
        action="store_true",
        help="Delete existing test sources before writing generated tests.",
    )
    # parser.add_argument(
    #     "--bug-path",
    #     type=str,
    #     help="Path to bugged code.",
    # )
    args = parser.parse_args()

    if args.delete_tests:
        delete_test_files_in_test_dirs(args.project_root, args.language)
    if args.data_path:
        write_generated_tests(args.project_root, args.data_path)

    # delete_test_files_in_test_dirs("projects/markitdown")
    # write_generated_tests("projects/flask", "fix_data.json")


# import json
# import subprocess
# import shutil
# from pathlib import Path
# from argparse import ArgumentParser


# def run_cmd(cmd, cwd):

#     r = subprocess.run(
#         cmd,
#         cwd=cwd,
#         stdout=subprocess.PIPE,
#         stderr=subprocess.PIPE
#     )

#     return r.returncode == 0


# def cargo_check(project):

#     return run_cmd(
#         ["cargo", "check", "--quiet"],
#         project
#     )


# def cargo_build(project):

#     return run_cmd(
#         ["cargo", "build", "--quiet"],
#         project
#     )


# def cargo_test(project):

#     return run_cmd(
#         ["cargo", "test", "--quiet"],
#         project
#     )


# def write_test(test_file, code):

#     with open(test_file, "a", encoding="utf8") as f:
#         f.write("\n\n")
#         f.write(code)
#         f.write("\n")


# def remove_test(test_file, code):

#     text = Path(test_file).read_text()

#     text = text.replace(code, "")

#     Path(test_file).write_text(text)


# def rename_test_module(code, name):

#     return code.replace(
#         "mod tests",
#         f"mod tests_{name}"
#     )


# def evaluate(json_file, project_root):

#     data = json.load(open(json_file))

#     project_root = Path(project_root)

#     syntax_pass = 0
#     compile_pass = 0
#     test_pass = 0
#     total = 0

#     results = []

#     print("Pre-build project (compile dependencies)...")

#     cargo_build(project_root)

#     for item in data:

#         if item["test_generation_status"] != "success":
#             continue

#         total += 1

#         name = item["name"]

#         test_file = project_root / item["test_file"]

#         test_codes = item["generated_tests"]

#         if not test_codes:
#             continue

#         code = test_codes[0]

#         code = rename_test_module(code, name)

#         write_test(test_file, code)

#         syntax_ok = cargo_check(project_root)

#         compile_ok = False
#         test_ok = False

#         if syntax_ok:

#             syntax_pass += 1

#             compile_ok = cargo_build(project_root)

#             if compile_ok:

#                 compile_pass += 1

#                 # test_ok = cargo_test(project_root)

#                 # if test_ok:
#                 #     test_pass += 1

#         results.append({
#             "name": name,
#             "syntax_pass": syntax_ok,
#             "compile_pass": compile_ok,
#             # "test_pass": test_ok
#         })

#         remove_test(test_file, code)

#         print(name, syntax_ok, compile_ok)

#     summary = {
#         "total": total,
#         "syntax_pass": syntax_pass,
#         "compile_pass": compile_pass,
#         # "test_pass": test_pass,
#         "syntax_pass_rate": syntax_pass / total if total else 0,
#         "compile_pass_rate": compile_pass / total if total else 0,
#         # "test_pass_rate": test_pass / total if total else 0,
#         "details": results
#     }

#     return summary


# if __name__ == "__main__":
#     parser = ArgumentParser()
#     parser.add_argument(
#         "--project-root",
#         type=str,
#         help="The root dir of project.",
#     )
#     parser.add_argument(
#         "--data-path",
#         type=str,
#         help="Path to data.",
#     )
#     args = parser.parse_args()

#     summary = evaluate(args.data_path, args.project_root)
