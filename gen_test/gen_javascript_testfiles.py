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
SKIP_DIRECTORY_NAMES = {".git", "node_modules", "dist", "build"}
JAVASCRIPT_TEST_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}


def delete_test_files_in_test_dirs(project_root):
    """按通用测试目录删除 JavaScript/TypeScript 测试源码，返回已删除路径。"""
    project_root = Path(project_root)
    deleted_files = []
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [directory for directory in dirs if directory not in SKIP_DIRECTORY_NAMES]
        root_path = Path(root)
        relative_root = root_path.relative_to(project_root)
        relative_parts = {part.lower() for part in relative_root.parts}
        if not relative_parts.intersection(TEST_DIRECTORY_NAMES):
            continue

        for filename in files:
            file_path = root_path / filename
            if file_path.suffix not in JAVASCRIPT_TEST_SUFFIXES:
                continue
            try:
                file_path.unlink()
                deleted_files.append(file_path)
            except OSError as error:
                print(f"删除失败 {file_path}: {error}")

    print(f"共删除 {len(deleted_files)} 个 JavaScript/TypeScript 测试源码文件")
    for file_path in deleted_files[:10]:
        print(f"  {file_path}")
    if len(deleted_files) > 10:
        print(f"  ... 还有 {len(deleted_files) - 10} 个文件")
    return deleted_files


def write_generated_tests(
    project_root,
    test_json_path,
    validation="rollup",
    jest_config=None,
    results_dir="/results",
):
    """生成测试文件（指定 utf-8 编码）"""
    try:
        with open(test_json_path, 'r', encoding='utf-8') as f:
            functions = json.load(f)
            print(len(functions.get("items", [])))

        project_root = Path(project_root).resolve()
        results_dir = Path(results_dir)
        results_dir.mkdir(parents=True, exist_ok=True)

        total = 0
        syntax_pass = 0
        compile_pass = 0
        # functions = [functions[0]]
        functions = functions["items"]
        generated_files = []
        for func in functions:
            # print(func)
            relative_test_file = Path(func.get("test_file", ""))
            test_file = (project_root / relative_test_file).resolve()
            if project_root not in test_file.parents:
                raise ValueError(f"测试路径越界: {relative_test_file}")

            test_file.parent.mkdir(parents=True, exist_ok=True)

            # raw_code = "\n\n".join(func["generated_tests"])
            raw_code = func["repair_history"][-1]["test_code"]
            # raw_code = func.get("generated_test_code", "")
#             raw_code = """
# const { primaryListener } = require('../../lib/cluster');

# // 事件类型常量。如果 cluster.js 从别的模块导入这些常量，
# // 改成从同一处导入，避免硬编码字符串不同步。
# const ANNOUNCEMENT = 'ANNOUNCEMENT';
# const GET_METRICS_RES = 'GET_METRICS_RES';
# const GOODBYE = 'GOODBYE';
# const ACK = 'ACK';

# // 造一个最小可用的 worker mock
# function makeWorker(id) {
# 	return {
# 		id,
# 		send: jest.fn(),
# 	};
# }

# describe('primaryListener', () => {
# 	describe('ANNOUNCEMENT', () => {
# 		test('注册新 worker 不抛异常', async () => {
# 			const worker = makeWorker(1);
# 			await expect(
# 				primaryListener(worker, { type: ANNOUNCEMENT })
# 			).resolves.toBeUndefined();
# 		});

# 		test('重复 announcement 被忽略', async () => {
# 			const worker = makeWorker(2);
# 			await primaryListener(worker, { type: ANNOUNCEMENT });
# 			// 第二次调用应走 "duplicate worker announcement" 分支，直接 return
# 			await expect(
# 				primaryListener(worker, { type: ANNOUNCEMENT })
# 			).resolves.toBeUndefined();
# 		});
# 	});

# 	describe('GET_METRICS_RES', () => {
# 		test('未知 requestId 被忽略', async () => {
# 			const worker = makeWorker(3);
# 			await expect(
# 				primaryListener(worker, {
# 					type: GET_METRICS_RES,
# 					requestId: 'does-not-exist',
# 					metrics: {},
# 				})
# 			).resolves.toBeUndefined();
# 		});

# 		test('未知 worker.id 被忽略', async () => {
# 			// 这个分支需要先把请求塞进 requests map，
# 			// 但 requests 是 cluster.js 的模块私有变量。
# 			// 如果你的测试环境用了 rewire，可以这样拿到它：
# 			//
# 			//   const rewire = require('rewire');
# 			//   const cluster = rewire('../../lib/cluster');
# 			//   const requests = cluster.__get__('requests');
# 			//   requests.set('r1', {
# 			//     responseHandlers: new Map(),
# 			//     workerFailures: 0,
# 			//   });
# 			//
# 			// 否则就跳过这个 case。
# 			expect(true).toBe(true);
# 		});
# 	});

# 	describe('GOODBYE', () => {
# 		test('已知 worker 会回 ACK 并被移除', async () => {
# 			const worker = makeWorker(4);

# 			// 先注册
# 			await primaryListener(worker, { type: ANNOUNCEMENT });

# 			// 再告别
# 			await primaryListener(worker, {
# 				type: GOODBYE,
# 				requestId: 'req-bye-1',
# 				metrics: [],
# 			});

# 			expect(worker.send).toHaveBeenCalledWith({
# 				type: ACK,
# 				requestId: 'req-bye-1',
# 			});
# 		});

# 		test('未知 worker 的 goodbye 不回 ACK', async () => {
# 			const worker = makeWorker(999);

# 			await primaryListener(worker, {
# 				type: GOODBYE,
# 				requestId: 'req-bye-2',
# 				metrics: [],
# 			});

# 			expect(worker.send).not.toHaveBeenCalled();
# 		});
# 	});

# 	describe('未知事件类型', () => {
# 		test('未知 type 不抛异常也不做事', async () => {
# 			const worker = makeWorker(5);
# 			await expect(
# 				primaryListener(worker, { type: 'SOMETHING_ELSE' })
# 			).resolves.toBeUndefined();
# 			expect(worker.send).not.toHaveBeenCalled();
# 		});
# 	});
# });
# """
            
            # 语法检查
             # 写入文件（UTF-8）
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write("\n\n" + raw_code)
            
            
            total += 1

            syntax_result = subprocess.run(
                ["node", "--check", str(test_file)],
                capture_output=True,
                text=True
            )
            syntax_ok = False
            if syntax_result.returncode == 0:
                syntax_ok = True
                syntax_pass += 1
            else:
                os.remove(test_file)
                print(f"[Syntax Error] Test:\n{syntax_result.stderr.strip()}\n")
            
            if syntax_ok:
                if validation == "rollup":
                    result = subprocess.run(
                        [
                            "npx", "rollup",
                            "-c", "rollup.temp.config.mjs",
                            "--input", str(test_file),
                        ],
                        capture_output=True,
                        text=True,
                        cwd=project_root,
                    )
                    success = result.returncode == 0
                    if success:
                        compile_pass += 1
                        generated_files.append(test_file)
                        print(f"写入 {test_file}")
                    else:
                        os.remove(test_file)
                        print(f"[Compile Error] Test :\n{result.stderr.strip()}\n")
                else:
                    generated_files.append(test_file)
                    print(f"写入 {test_file}")

                # exec_result = subprocess.run(
                #     ["node", str(test_file)],
                #     capture_output=True,
                #     text=True
                # )
                # if exec_result.returncode == 0:
                #     # compile_ok = True
                #     compile_pass += 1
                # else:
                #     os.remove(test_file)
                #     print(f"[Compile/Runtime Error] Test :\n{exec_result.stderr.strip()}\n")
        
        jest_result = None
        if validation == "jest" and generated_files:
            command = ["jest", "--runInBand", "--runTestsByPath"]
            command.extend(str(path) for path in generated_files)
            if jest_config:
                command.extend(["--config", str(jest_config)])
            jest_result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                cwd=project_root,
            )
            print(jest_result.stdout, end="")
            print(jest_result.stderr, end="", file=sys.stderr)
            if jest_result.returncode == 0:
                compile_pass = len(generated_files)

        with open(results_dir / "test_results_summary.txt", 'w', encoding='utf-8') as summary_file:
            summary_file.write(f"Total tests generated: {total}\n")
            syntax_rate = syntax_pass / total * 100 if total else 0
            compile_rate = compile_pass / total * 100 if total else 0
            summary_file.write(f"Syntax check passed: {syntax_pass} ({syntax_rate:.2f}%)\n")
            summary_file.write(f"Compile/runtime check passed: {compile_pass} ({compile_rate:.2f}%)\n")

        if syntax_pass != total or compile_pass != total:
            return False
        if jest_result is not None and jest_result.returncode != 0:
            return False
        return True

    except Exception as e:
        print(f"写入文件失败: {e}")
        return False

# def write_generated_tests(project_root, test_json_path):
#     """生成测试文件（指定 utf-8 编码）"""
#     try:
#         with open(test_json_path, 'r', encoding='utf-8') as f:
#             functions = json.load(f)
#             print(len(functions))


#         for func in functions["items"]:
#             # print(func)
            
            
#             test_file = "/testbed"+ "/" + func.get("test_file")

#             dir_path = os.path.dirname(test_file)
#             if not os.path.exists(dir_path):
#                 os.makedirs(dir_path, exist_ok=True)

#             # raw_code = "\n\n".join(func["generated_tests"])
#             # raw_code = func.get("generated_test_code", "")
#             raw_code = func["repair_history"][-1]["test_code"]
            
#             # 语法检查
#              # 写入文件（UTF-8）
#             with open(test_file, 'w', encoding='utf-8') as f:
#                 f.write("\n\n" + raw_code)
#             print(f"写入 {test_file}")
            
         

#     except Exception as e:
#         print(f"写入文件失败: {e}")



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
        "--validation",
        choices=("rollup", "jest"),
        default="rollup",
        help="生成后的验证方式，默认保持原有 Rollup 验证。",
    )
    parser.add_argument("--jest-config", help="Jest 配置文件路径。")
    parser.add_argument(
        "--results-dir",
        default="/results",
        help="汇总文件输出目录，默认 /results。",
    )
    args = parser.parse_args()

    delete_test_files_in_test_dirs(args.project_root)
    success = write_generated_tests(
        args.project_root,
        args.data_path,
        validation=args.validation,
        jest_config=args.jest_config,
        results_dir=args.results_dir,
    )
    raise SystemExit(0 if success else 1)

    # delete_test_files_in_test_dirs("projects/markitdown")
    # write_generated_tests("projects/markitdown", "markitdown_lite_specification_unittest_gpt4o.json")
