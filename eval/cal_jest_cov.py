# import json
# import os

# def load_coverage(json_path="test_results/simple-statistics/jest_DSv3.2/coverage/coverage-final.json"):
#     """加载 coverage-final.json 文件"""
#     with open(json_path, 'r', encoding='utf-8') as f:
#         return json.load(f)

# def get_function_coverage(file_data):
#     """
#     从单个文件的覆盖率数据中提取每个函数的行和分支覆盖率
#     返回一个列表，每个元素为 (函数名, 覆盖行数, 总行数, 行覆盖率, 覆盖分支数, 总分支数, 分支覆盖率)
#     """
#     statement_map = file_data.get('statementMap', {})
#     s_hits = file_data.get('s', {})
#     fn_map = file_data.get('fnMap', {})
#     branch_map = file_data.get('branchMap', {})
#     b_hits = file_data.get('b', {})

#     results = []

#     # 如果没有函数映射，直接返回空
#     if not fn_map:
#         return results

#     # 构建每个语句覆盖的行集合
#     stmt_lines = {}  # 语句ID -> 该语句覆盖的行号集合
#     for stmt_id, stmt in statement_map.items():
#         start = stmt['start']['line']
#         end = stmt['end']['line']
#         lines = set(range(start, end + 1))
#         stmt_lines[stmt_id] = lines

#     # 遍历每个函数
#     for fn_id, fn_info in fn_map.items():
#         fn_name = fn_info['name']
#         fn_start = fn_info['loc']['start']['line']
#         fn_end = fn_info['loc']['end']['line']

#         # 收集属于该函数的语句ID
#         function_stmt_ids = []
#         for stmt_id, stmt in statement_map.items():
#             # 判断语句的起始行是否在函数范围内（语句主体在函数内）
#             if fn_start <= stmt['start']['line'] <= fn_end:
#                 function_stmt_ids.append(stmt_id)

#         if not function_stmt_ids:
#             # 函数内没有可执行语句（理论上不可能，但防御性处理）
#             results.append((fn_name, 0, 0, 1.0, 0, 0, 1.0))
#             continue

#         # 计算函数内的总行数（所有语句覆盖行的并集）
#         total_lines = set()
#         for stmt_id in function_stmt_ids:
#             total_lines.update(stmt_lines[stmt_id])

#         # 计算覆盖的行数（被执行的语句覆盖的行）
#         covered_lines = set()
#         for stmt_id in function_stmt_ids:
#             if s_hits.get(stmt_id, 0) > 0:
#                 covered_lines.update(stmt_lines[stmt_id])

#         line_covered = len(covered_lines)
#         line_total = len(total_lines)
#         line_coverage = line_covered / line_total if line_total > 0 else 1.0

#         # 处理分支覆盖率
#         total_branches = 0
#         covered_branches = 0
#         for branch_id, branch in branch_map.items():
#             # 检查分支是否属于该函数（以分支起始行为准）
#             if fn_start <= branch['line'] <= fn_end:
#                 # 该分支可能有多个位置，每个位置对应一个分支点
#                 branch_hits = b_hits.get(branch_id, [])
#                 # branch_hits 的长度应与分支点数一致
#                 for hit in branch_hits:
#                     total_branches += 1
#                     if hit > 0:
#                         covered_branches += 1

#         branch_coverage = covered_branches / total_branches if total_branches > 0 else 1.0

#         results.append((
#             fn_name,
#             line_covered, line_total, line_coverage,
#             covered_branches, total_branches, branch_coverage
#         ))

#     return results

# def main():
#     data = load_coverage()

#     for file_path, file_data in data.items():
#         # 提取文件名（短路径）
#         short_path = os.path.basename(file_path)
#         functions = get_function_coverage(file_data)
#         if not functions:
#             continue

#         print(f"\n文件: {short_path} ({file_path})")
#         for (fn_name,
#              line_cov, line_total, line_pct,
#              branch_cov, branch_total, branch_pct) in functions:

#             print(f"  函数: {fn_name}")
#             print(f"    行覆盖率: {line_cov}/{line_total} ({line_pct:.2%})")
#             if branch_total > 0:
#                 print(f"    分支覆盖率: {branch_cov}/{branch_total} ({branch_pct:.2%})")
#             else:
#                 print(f"    分支覆盖率: 无分支 (100%)")

# if __name__ == "__main__":
#     main()

#!/usr/bin/env python3
# """Parse Jest coverage-final.json and report per-function line/branch coverage."""

# from __future__ import annotations

# import argparse
# import json
# from pathlib import Path
# from typing import Dict, Iterable, List, Set, Tuple


# def expand_lines(start_line: int, end_line: int) -> Set[int]:
#     if end_line < start_line:
#         return set()
#     return set(range(start_line, end_line + 1))


# def statements_by_function(file_cov: dict, fn_data: dict) -> Tuple[int, int]:
#     """Return (covered_lines, total_lines) derived from statement ranges inside function loc."""
#     fn_start = fn_data["loc"]["start"]["line"]
#     fn_end = fn_data["loc"]["end"]["line"]

#     total_lines: Set[int] = set()
#     covered_lines: Set[int] = set()

#     statement_map = file_cov.get("statementMap", {})
#     statement_hits = file_cov.get("s", {})

#     for stmt_id, stmt_loc in statement_map.items():
#         stmt_start = stmt_loc["start"]["line"]
#         stmt_end = stmt_loc["end"]["line"]

#         if stmt_start < fn_start or stmt_end > fn_end:
#             continue

#         stmt_lines = expand_lines(stmt_start, stmt_end)
#         total_lines.update(stmt_lines)

#         if statement_hits.get(stmt_id, 0) > 0:
#             covered_lines.update(stmt_lines)

#     return len(covered_lines), len(total_lines)


# def branches_by_function(file_cov: dict, fn_data: dict) -> Tuple[int, int]:
#     """Return (covered_branches, total_branches) for branches located inside function loc."""
#     fn_start = fn_data["loc"]["start"]["line"]
#     fn_end = fn_data["loc"]["end"]["line"]

#     branch_map = file_cov.get("branchMap", {})
#     branch_hits = file_cov.get("b", {})

#     covered = 0
#     total = 0

#     for branch_id, branch_data in branch_map.items():
#         line = branch_data.get("line")
#         if line is None:
#             line = branch_data.get("loc", {}).get("start", {}).get("line")

#         if line is None or line < fn_start or line > fn_end:
#             continue

#         hits = branch_hits.get(branch_id, [])
#         total += len(hits)
#         covered += sum(1 for h in hits if h > 0)

#     return covered, total


# def pct(covered: int, total: int) -> str:
#     if total == 0:
#         return "N/A"
#     return f"{(covered / total) * 100:.2f}%"


# def iter_results(coverage_data: Dict[str, dict]) -> Iterable[dict]:
#     for file_path, file_cov in coverage_data.items():
#         fn_map = file_cov.get("fnMap", {})
#         if not fn_map:
#             continue

#         for fn_id, fn_data in fn_map.items():
#             fn_name = fn_data.get("name") or f"<anonymous:{fn_id}>"
#             fn_line = fn_data.get("line")

#             covered_lines, total_lines = statements_by_function(file_cov, fn_data)
#             covered_branches, total_branches = branches_by_function(file_cov, fn_data)

#             yield {
#                 "file": file_path,
#                 "function": fn_name,
#                 "line": fn_line,
#                 "line_covered": covered_lines,
#                 "line_total": total_lines,
#                 "line_pct": pct(covered_lines, total_lines),
#                 "branch_covered": covered_branches,
#                 "branch_total": total_branches,
#                 "branch_pct": pct(covered_branches, total_branches),
#             }


# def main() -> None:
#     parser = argparse.ArgumentParser(
#         description="Report per-function line/branch coverage from Jest coverage-final.json"
#     )
#     parser.add_argument("coverage_file", type=Path, help="Path to coverage-final.json")
#     parser.add_argument(
#         "--json",
#         action="store_true",
#         help="Output JSON instead of a text table",
#     )
#     args = parser.parse_args()

#     with args.coverage_file.open("r", encoding="utf-8") as f:
#         coverage_data = json.load(f)

#     results = list(iter_results(coverage_data))

#     if args.json:
#         print(json.dumps(results, ensure_ascii=False, indent=2))
#         return

#     if not results:
#         print("No function coverage data found.")
#         return

#     header = (
#         "file",
#         "function",
#         "line",
#         "line_cov",
#         "line_total",
#         "line_%",
#         "branch_cov",
#         "branch_total",
#         "branch_%",
#     )
#     print("\t".join(header))
#     for r in results:
#         print(
#             "\t".join(
#                 [
#                     str(r["file"]),
#                     str(r["function"]),
#                     str(r["line"]),
#                     str(r["line_covered"]),
#                     str(r["line_total"]),
#                     str(r["line_pct"]),
#                     str(r["branch_covered"]),
#                     str(r["branch_total"]),
#                     str(r["branch_pct"]),
#                 ]
#             )
#         )


# if __name__ == "__main__":
#     main()


import os
import json


# def compute_file_metrics(file_cov):
#     statement_map = file_cov["statementMap"]
#     fn_map = file_cov.get("fnMap", {})
#     branch_map = file_cov.get("branchMap", {})

#     s = file_cov.get("s", {})
#     b = file_cov.get("b", {})

#     # ========================
#     # 1 文件级 line coverage
#     # ========================

#     total_lines = set()
#     covered_lines = set()

#     for sid, stmt in statement_map.items():
#         line = stmt["start"]["line"]

#         total_lines.add(line)

#         if s.get(sid, 0) > 0:
#             covered_lines.add(line)

#     file_line_cov = (
#         len(covered_lines) / len(total_lines) if total_lines else 1
#     )

#     # ========================
#     # 2 文件级 branch coverage
#     # ========================

#     total_branches = 0
#     covered_branches = 0

#     for bid, hits in b.items():

#         total_branches += len(hits)

#         for h in hits:
#             if h > 0:
#                 covered_branches += 1

#     file_branch_cov = (
#         covered_branches / total_branches if total_branches else 1
#     )

#     # ========================
#     # 3 函数级覆盖率
#     # ========================

#     functions = {}

#     for fid, fn in fn_map.items():

#         name = fn.get("name") or f"fn_{fid}"

#         start = fn["loc"]["start"]["line"]
#         end = fn["loc"]["end"]["line"]

#         fn_lines = set()
#         fn_lines_covered = set()

#         # ---------- line coverage ----------

#         for sid, stmt in statement_map.items():

#             line = stmt["start"]["line"]

#             if start <= line <= end:

#                 fn_lines.add(line)

#                 if s.get(sid, 0) > 0:
#                     fn_lines_covered.add(line)

#         fn_line_cov = (
#             len(fn_lines_covered) / len(fn_lines)
#             if fn_lines
#             else 1
#         )

#         # ---------- branch coverage ----------

#         fn_total_branches = 0
#         fn_covered_branches = 0

#         for bid, br in branch_map.items():

#             branch_line = br["line"]

#             if start <= branch_line <= end:

#                 hits = b.get(bid, [])

#                 fn_total_branches += len(hits)

#                 for h in hits:
#                     if h > 0:
#                         fn_covered_branches += 1

#         fn_branch_cov = (
#             fn_covered_branches / fn_total_branches
#             if fn_total_branches
#             else 1
#         )

#         # ---------- 是否触达函数 ----------

#         fn_hit = False
#         for sid, stmt in statement_map.items():
#             line = stmt["start"]["line"]

#             if start <= line <= end and s.get(sid, 0) > 0:
#                 fn_hit = True
#                 break

#         functions[name] = {
#             "start_line": start,
#             "end_line": end,
#             "hit": fn_hit,
#             "line_coverage": fn_line_cov,
#             "branch_coverage": fn_branch_cov,
#             "total_lines": len(fn_lines),
#             "covered_lines": len(fn_lines_covered),
#             "total_branches": fn_total_branches,
#             "covered_branches": fn_covered_branches,
#         }

#     return {
#         "file_line_coverage": file_line_cov,
#         "file_branch_coverage": file_branch_cov,
#         "total_lines": len(total_lines),
#         "covered_lines": len(covered_lines),
#         "functions": functions,
#     }


# def parse_coverage(test_result_dir, coverage_path):

#     result = {}
#     with open(coverage_path) as f:
#         coverage = json.load(f)

#     for file_path, file_cov in coverage.items():

#         result[file_path] = compute_file_metrics(file_cov)

#     with open(os.path.join(test_result_dir, "cov-summary.json"), 'w', encoding='utf-8') as f:
#         json.dump(result, f, indent=2, ensure_ascii=False)

#     return result


# def compute_only_reached_functions(metrics):

#     total_lines = 0
#     covered_lines = 0

#     total_branches = 0
#     covered_branches = 0

#     for file in metrics.values():

#         for fn in file["functions"].values():

#             if not fn["hit"]:
#                 continue

#             total_lines += fn["total_lines"]
#             covered_lines += fn["covered_lines"]

#             total_branches += fn["total_branches"]
#             covered_branches += fn["covered_branches"]

#     return {
#         "line_coverage": covered_lines / total_lines if total_lines else 1,
#         "branch_coverage": covered_branches / total_branches if total_branches else 1,
#     }


# if __name__ == "__main__":

#     # with open("test_results/simple-statistics/jest_DSv3.2/coverage/coverage-final.json") as f:
#     #     coverage = json.load(f)

#     # metrics = parse_coverage(coverage)

#     # reached_metrics = compute_only_reached_functions(metrics)

#     print(json.dumps(metrics, indent=2))

#     with open("test_results/simple-statistics/jest_DSv3.2/cov-summary.json", 'w', encoding='utf-8') as f:
#         json.dump(metrics, f, indent=2, ensure_ascii=False)

#     # print("\nReached Functions Coverage:")
#     # print(json.dumps(reached_metrics, indent=2))





# 处理单个测试（例如jest_glm目录）的覆盖率,用fnmap
# import json


# def get_branch_line(br):
#     """
#     获取 branch 的源码行号
#     兼容所有 Istanbul branch 类型
#     """

#     line = br.get("line")
#     if line:
#         return line

#     loc = br.get("loc")
#     if loc and "start" in loc:
#         return loc["start"].get("line")

#     for loc in br.get("locations", []):
#         start = loc.get("start")
#         if start and "line" in start:
#             return start["line"]

#     return None


# def compute_file_metrics(file_cov, focal_functions):

#     statement_map = file_cov.get("statementMap", {})
#     fn_map = file_cov.get("fnMap", {})
#     branch_map = file_cov.get("branchMap", {})

#     s = file_cov.get("s", {})
#     b = file_cov.get("b", {})

#     # =========================
#     # file line coverage
#     # =========================

#     total_lines = set()
#     covered_lines = set()

#     for sid, stmt in statement_map.items():

#         line = stmt["start"]["line"]

#         total_lines.add(line)

#         if s.get(sid, 0) > 0:
#             covered_lines.add(line)

#     file_line_cov = (
#         len(covered_lines) / len(total_lines) if total_lines else 1
#     )

#     # =========================
#     # file branch coverage
#     # =========================

#     total_branches = 0
#     covered_branches = 0

#     for bid, hits in b.items():

#         total_branches += len(hits)

#         # for h in hits:
#         #     if h > 0:
#         #         covered_branches += 1

#         for h in hits:
#             if (h or 0) > 0:
#                 covered_branches += 1

#     file_branch_cov = (
#         covered_branches / total_branches if total_branches else 1
#     )

#     # =========================
#     # function metrics
#     # =========================

#     functions = {}

#     for fid, fn in fn_map.items():

#         name = fn.get("name")
#         if name not in focal_functions:
#             continue

#         start = fn["loc"]["start"]["line"]
#         end = fn["loc"]["end"]["line"]

#         fn_lines = set()
#         fn_lines_covered = set()

#         # ---------- line coverage ----------

#         for sid, stmt in statement_map.items():

#             line = stmt["start"]["line"]

#             if start <= line <= end:

#                 fn_lines.add(line)

#                 if s.get(sid, 0) > 0:
#                     fn_lines_covered.add(line)

#         fn_line_cov = (
#             len(fn_lines_covered) / len(fn_lines)
#             if fn_lines
#             else 1
#         )

#         # ---------- branch coverage ----------

#         fn_total_branches = 0
#         fn_covered_branches = 0

#         for bid, hits in b.items():

#             br = branch_map.get(bid)
#             if not br:
#                 continue

#             branch_line = get_branch_line(br)

#             if branch_line is None:
#                 continue

#             if start <= branch_line <= end:

#                 fn_total_branches += len(hits)

#                 # for h in hits:
#                 #     if h > 0:
#                 #         fn_covered_branches += 1

#                 for h in hits:
#                     if (h or 0) > 0:
#                         fn_covered_branches += 1

#         fn_branch_cov = (
#             fn_covered_branches / fn_total_branches
#             if fn_total_branches
#             else 1
#         )

#         # ---------- function hit ----------

#         fn_hit = False

#         for sid, stmt in statement_map.items():

#             line = stmt["start"]["line"]

#             if start <= line <= end and s.get(sid, 0) > 0:
#                 fn_hit = True
#                 break

#         functions[name] = {
#             "start_line": start,
#             "end_line": end,
#             "hit": fn_hit,
#             "line_coverage": fn_line_cov,
#             "branch_coverage": fn_branch_cov,
#             "total_lines": len(fn_lines),
#             "covered_lines": len(fn_lines_covered),
#             "total_branches": fn_total_branches,
#             "covered_branches": fn_covered_branches,
#         }

#     return {
#         "file_line_coverage": file_line_cov,
#         "file_branch_coverage": file_branch_cov,
#         "total_lines": len(total_lines),
#         "covered_lines": len(covered_lines),
#         "total_branches": total_branches,
#         "covered_branches": covered_branches,
#         "functions": functions,
#     }


# def parse_coverage(test_result_dir, coverage_path, data_file):

#     # 读取过滤数据
#     with open(data_file) as f:
#         data = json.load(f)

#     # 构建过滤映射
#     file_functions = {}  # src_file -> set(function_names)
#     for item in data:
#         src_file = item.get("src_file")
#         name = item.get("name")
#         if src_file and name:
#             file_functions.setdefault(src_file, set()).add(name)

#     with open(coverage_path) as f:
#         coverage = json.load(f)

#     result = {}

#     for file_path, file_cov in coverage.items():
#         file_path = file_path.replace('/testbed/', '')
#         if file_path not in file_functions:
#             continue

#         result[file_path] = compute_file_metrics(file_cov, file_functions.get(file_path, set()))

#     # with open(os.path.join(test_result_dir, "cov-summary.json"), 'w', encoding='utf-8') as f:
#     #     json.dump(result, f, indent=2, ensure_ascii=False)
#     final_result = build_global_summary(result)

#     return final_result


# def compute_reached_function_metrics(metrics):

#     total_lines = 0
#     covered_lines = 0

#     total_branches = 0
#     covered_branches = 0

#     for file in metrics.values():

#         for fn in file["functions"].values():

#             if not fn["hit"]:
#                 continue

#             total_lines += fn["total_lines"]
#             covered_lines += fn["covered_lines"]

#             total_branches += fn["total_branches"]
#             covered_branches += fn["covered_branches"]

#     return {
#         "line_coverage": covered_lines / total_lines if total_lines else 1,
#         "branch_coverage": covered_branches / total_branches if total_branches else 1,
#     }


# def build_global_summary(metrics):
#     """
#     metrics: parse_coverage 返回结果
#     """

#     file_result = {}
#     function_result = {}

#     total_file_lines = 0
#     total_file_covered_lines = 0
#     total_file_branches = 0
#     total_file_covered_branches = 0

#     total_fn_lines = 0
#     total_fn_covered_lines = 0
#     total_fn_branches = 0
#     total_fn_covered_branches = 0

#     for file_path, file_data in metrics.items():

#         # =========================
#         # file级统计
#         # =========================
#         file_result[file_path] = {
#             "total_lines": file_data["total_lines"],
#             "covered_lines": file_data["covered_lines"],
#             "total_branches": file_data["total_branches"],
#             "covered_branches": file_data["covered_branches"],
#         }

#         total_file_lines += file_data["total_lines"]
#         total_file_covered_lines += file_data["covered_lines"]
#         total_file_branches += file_data["total_branches"]
#         total_file_covered_branches += file_data["covered_branches"]

#         # =========================
#         # function级统计
#         # =========================
#         for fn_key, fn in file_data["functions"].items():

#             global_fn_name = f"{file_path}::{fn_key}"

#             function_result[global_fn_name] = {
#                 "total_lines": fn["total_lines"],
#                 "covered_lines": fn["covered_lines"],
#                 "total_branches": fn["total_branches"],
#                 "covered_branches": fn["covered_branches"],
#             }

#             total_fn_lines += fn["total_lines"]
#             total_fn_covered_lines += fn["covered_lines"]
#             total_fn_branches += fn["total_branches"]
#             total_fn_covered_branches += fn["covered_branches"]

#     # =========================
#     # summary
#     # =========================
#     summary = {
#         "file": {
#             "total_lines": total_file_lines,
#             "covered_lines": total_file_covered_lines,
#             "total_branches": total_file_branches,
#             "covered_branches": total_file_covered_branches,
#         },
#         "function": {
#             "total_lines": total_fn_lines,
#             "covered_lines": total_fn_covered_lines,
#             "total_branches": total_fn_branches,
#             "covered_branches": total_fn_covered_branches,
#         }
#     }

#     return {
#         "file": file_result,
#         "function": function_result,
#         "summary": summary
#     }














# 处理单个测试（例如jest_glm目录）的覆盖率,不用fnmap，用的是带行号的数据集
import json
import os


def normalize_path(path):
    """统一路径格式，方便和 JSON 里的 src_file 对齐"""
    if not path:
        return path
    path = path.replace("\\", "/")
    path = path.replace("/testbed/", "")
    path = path.lstrip("./")
    return path


def get_branch_line(br):
    """
    获取 branch 的源码行号
    兼容所有 Istanbul branch 类型
    """
    line = br.get("line")
    if line:
        return line

    loc = br.get("loc")
    if loc and "start" in loc:
        return loc["start"].get("line")

    for loc in br.get("locations", []):
        start = loc.get("start")
        if start and "line" in start:
            return start["line"]

    return None


def compute_file_metrics(file_cov, focal_functions):
    """
    只统计 focal_functions 中出现的函数。
    函数边界使用 start_line / end_line，
    不再依赖 fnMap。
    """

    statement_map = file_cov.get("statementMap", {})
    branch_map = file_cov.get("branchMap", {})

    s = file_cov.get("s", {})
    b = file_cov.get("b", {})

    # =========================
    # file line coverage
    # =========================
    total_lines = set()
    covered_lines = set()

    for sid, stmt in statement_map.items():
        start = stmt.get("start", {})
        line = start.get("line")
        if line is None:
            continue

        total_lines.add(line)
        if s.get(sid, 0) > 0:
            covered_lines.add(line)

    file_line_cov = len(covered_lines) / len(total_lines) if total_lines else 1

    # =========================
    # file branch coverage
    # =========================
    total_branches = 0
    covered_branches = 0

    for bid, hits in b.items():
        total_branches += len(hits)
        for h in hits:
            if (h or 0) > 0:
                covered_branches += 1

    file_branch_cov = covered_branches / total_branches if total_branches else 1

    # =========================
    # function metrics
    # =========================
    functions = {}

    for fn in focal_functions:
        name = fn.get("name")
        start = fn.get("start_line")
        end = fn.get("end_line")

        if name is None or start is None or end is None:
            continue

        fn_lines = set()
        fn_lines_covered = set()

        # ---------- line coverage ----------
        for sid, stmt in statement_map.items():
            line = stmt.get("start", {}).get("line")
            if line is None:
                continue

            if start <= line <= end:
                fn_lines.add(line)
                if s.get(sid, 0) > 0:
                    fn_lines_covered.add(line)

        fn_line_cov = len(fn_lines_covered) / len(fn_lines) if fn_lines else 1

        # ---------- branch coverage ----------
        fn_total_branches = 0
        fn_covered_branches = 0

        for bid, hits in b.items():
            br = branch_map.get(bid)
            if not br:
                continue

            branch_line = get_branch_line(br)
            if branch_line is None:
                continue

            if start <= branch_line <= end:
                fn_total_branches += len(hits)
                for h in hits:
                    if (h or 0) > 0:
                        fn_covered_branches += 1

        fn_branch_cov = (
            fn_covered_branches / fn_total_branches if fn_total_branches else 1
        )

        # ---------- function hit ----------
        fn_hit = False
        for sid, stmt in statement_map.items():
            line = stmt.get("start", {}).get("line")
            if line is None:
                continue
            if start <= line <= end and s.get(sid, 0) > 0:
                fn_hit = True
                break

        # 用 name + 行号避免同名函数冲突
        fn_key = f"{name}:{start}-{end}"

        functions[fn_key] = {
            "name": name,
            "start_line": start,
            "end_line": end,
            "hit": fn_hit,
            "line_coverage": fn_line_cov,
            "branch_coverage": fn_branch_cov,
            "total_lines": len(fn_lines),
            "covered_lines": len(fn_lines_covered),
            "total_branches": fn_total_branches,
            "covered_branches": fn_covered_branches,
            # 可选保留这些字段，方便后续分析
            "type": fn.get("type"),
            "class_name": fn.get("class_name"),
            "full_class_name": fn.get("full_class_name"),
            "test_file": fn.get("test_file"),
            "src_file": fn.get("src_file"),
        }

    return {
        "file_line_coverage": file_line_cov,
        "file_branch_coverage": file_branch_cov,
        "total_lines": len(total_lines),
        "covered_lines": len(covered_lines),
        "total_branches": total_branches,
        "covered_branches": covered_branches,
        "functions": functions,
    }


def parse_coverage(test_result_dir, coverage_path, data_file):
    """
    data_file: 你单独保存的函数元信息 JSON
    coverage_path: Istanbul / nyc coverage 报告 JSON
    """

    # 读取函数元信息
    with open(data_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 构建映射: src_file -> [function_info, ...]
    file_functions = {}
    for item in data:
        src_file = normalize_path(item.get("src_file"))
        if not src_file:
            continue
        file_functions.setdefault(src_file, []).append(item)

    # 读取 coverage
    with open(coverage_path, "r", encoding="utf-8") as f:
        coverage = json.load(f)

    result = {}

    for file_path, file_cov in coverage.items():
        file_path = normalize_path(file_path)

        if file_path not in file_functions:
            continue

        result[file_path] = compute_file_metrics(
            file_cov,
            file_functions[file_path]
        )

    # 全局汇总
    final_result = build_global_summary(result)

    with open(os.path.join(test_result_dir, "cov-summary1.json"), "w", encoding="utf-8") as f:
        json.dump(final_result, f, indent=2, ensure_ascii=False)

    return final_result


def compute_reached_function_metrics(metrics):
    total_lines = 0
    covered_lines = 0

    total_branches = 0
    covered_branches = 0

    for file in metrics.values():
        for fn in file["functions"].values():
            if not fn["hit"]:
                continue

            total_lines += fn["total_lines"]
            covered_lines += fn["covered_lines"]

            total_branches += fn["total_branches"]
            covered_branches += fn["covered_branches"]

    return {
        "line_coverage": covered_lines / total_lines if total_lines else 1,
        "branch_coverage": covered_branches / total_branches if total_branches else 1,
    }

def build_global_summary(metrics):
    """
    metrics: parse_coverage 返回结果
    """

    file_result = {}
    function_result = {}

    total_file_lines = 0
    total_file_covered_lines = 0
    total_file_branches = 0
    total_file_covered_branches = 0

    total_fn_lines = 0
    total_fn_covered_lines = 0
    total_fn_branches = 0
    total_fn_covered_branches = 0

    for file_path, file_data in metrics.items():

        # =========================
        # file级统计
        # =========================
        file_result[file_path] = {
            "total_lines": file_data["total_lines"],
            "covered_lines": file_data["covered_lines"],
            "total_branches": file_data["total_branches"],
            "covered_branches": file_data["covered_branches"],
        }

        total_file_lines += file_data["total_lines"]
        total_file_covered_lines += file_data["covered_lines"]
        total_file_branches += file_data["total_branches"]
        total_file_covered_branches += file_data["covered_branches"]

        # =========================
        # function级统计
        # =========================
        for fn_key, fn in file_data["functions"].items():

            global_fn_name = f"{file_path}::{fn_key}"

            function_result[global_fn_name] = {
                "total_lines": fn["total_lines"],
                "covered_lines": fn["covered_lines"],
                "total_branches": fn["total_branches"],
                "covered_branches": fn["covered_branches"],
            }

            total_fn_lines += fn["total_lines"]
            total_fn_covered_lines += fn["covered_lines"]
            total_fn_branches += fn["total_branches"]
            total_fn_covered_branches += fn["covered_branches"]

    # =========================
    # summary
    # =========================
    summary = {
        "file": {
            "total_lines": total_file_lines,
            "covered_lines": total_file_covered_lines,
            "total_branches": total_file_branches,
            "covered_branches": total_file_covered_branches,
        },
        "function": {
            "total_lines": total_fn_lines,
            "covered_lines": total_fn_covered_lines,
            "total_branches": total_fn_branches,
            "covered_branches": total_fn_covered_branches,
        }
    }

    return {
        "file": file_result,
        "function": function_result,
        "summary": summary
    }

# parse_coverage("test_results/javascript/modern-error/jest_DS6.7b", "test_results/javascript/modern-error/jest_DS6.7b/coverage/coverage-final.json", "data_file.json")




# # 调用上面的 parse_coverage 处理一个大目录下的多个测试结果
# import os


# def find_coverage_files(root_dir):
#     """
#     遍历目录，找到所有 coverage-final.json
#     """
#     coverage_files = []

#     for dirpath, dirnames, filenames in os.walk(root_dir):
#         if "coverage-final.json" in filenames:
#             coverage_path = os.path.join(dirpath, "coverage-final.json")
#             coverage_files.append(coverage_path)

#     return coverage_files


# def batch_parse_coverage(root_dir, data_file):

#     coverage_files = find_coverage_files(root_dir)

#     print(f"找到 {len(coverage_files)} 个 coverage 文件")

#     for cov_path in coverage_files:

#         # coverage目录
#         coverage_dir = os.path.dirname(cov_path)

#         # 👉 上一级目录（目标输出位置）
#         project_dir = os.path.dirname(coverage_dir)

#         print(f"\n处理: {project_dir}")

#         try:
#             parse_coverage(
#                 test_result_dir=project_dir,   # 👈 关键修改
#                 coverage_path=cov_path,
#                 data_file=data_file
#             )

#         except Exception as e:
#             print(f"❌ 失败: {project_dir} -> {e}")

#     print("\n全部处理完成")


# if __name__ == "__main__":
#     ROOT_DIR = "test_results/javascript/simple-statistics"       # 大目录
#     DATA_FILE = "data_file.json"    # 你的函数信息
#     # OUTPUT_DIR = "output"           # 输出目录

#     batch_parse_coverage(ROOT_DIR, DATA_FILE)













# import json
# import os

# def get_branch_line(br):
#     """
#     获取 branch 的源码行号
#     兼容所有 Istanbul branch 类型
#     """
#     line = br.get("line")
#     if line:
#         return line

#     loc = br.get("loc")
#     if loc and "start" in loc:
#         return loc["start"].get("line")

#     for loc in br.get("locations", []):
#         start = loc.get("start")
#         if start and "line" in start:
#             return start["line"]

#     return None


# def parse_coverage(test_result_dir, coverage_path, data_file_path):
#     """
#     解析覆盖率文件，仅统计 data_file.json 中列出的文件及函数，
#     输出包含文件级、函数级及汇总的 JSON 结构。
#     """
#     # 读取覆盖率数据
#     with open(coverage_path) as f:
#         coverage = json.load(f)

#     # 读取过滤数据
#     with open(data_file_path) as f:
#         data = json.load(f)

#     # 构建过滤映射
#     file_functions = {}  # src_file -> set(function_names)
#     for item in data:
#         src_file = item.get("src_file")
#         name = item.get("name")
#         if src_file and name:
#             file_functions.setdefault(src_file, set()).add(name)

#     # 存储结果
#     file_stats = {}
#     function_stats = {}

#     # 遍历覆盖率文件
#     for file_path, file_cov in coverage.items():
#         file_path = file_path.replace('/testbed/', '')
#         # 仅处理需要统计的文件
#         if file_path not in file_functions:
#             continue

#         allowed_functions = file_functions[file_path]

#         statement_map = file_cov.get("statementMap", {})
#         fn_map = file_cov.get("fnMap", {})
#         branch_map = file_cov.get("branchMap", {})
#         s = file_cov.get("s", {})
#         b = file_cov.get("b", {})

#         # 文件级集合（去重）
#         file_lines = set()
#         file_covered_lines = set()
#         file_total_branches = 0
#         file_covered_branches = 0

#         # 遍历函数
#         for fid, fn in fn_map.items():
#             name = fn.get("name") or f"fn_{fid}"
#             if name not in allowed_functions:
#                 continue

#             # 函数范围
#             start = fn["loc"]["start"]["line"]
#             end = fn["loc"]["end"]["line"]

#             # 函数级统计
#             fn_lines = set()
#             fn_covered_lines = set()
#             fn_total_branches = 0
#             fn_covered_branches = 0

#             # 行覆盖
#             for sid, stmt in statement_map.items():
#                 line = stmt["start"]["line"]
#                 if start <= line <= end:
#                     fn_lines.add(line)
#                     if s.get(sid, 0) > 0:
#                         fn_covered_lines.add(line)

#             # 分支覆盖
#             for bid, hits in b.items():
#                 br = branch_map.get(bid)
#                 if not br:
#                     continue
#                 branch_line = get_branch_line(br)
#                 if branch_line is None:
#                     continue
#                 if start <= branch_line <= end:
#                     fn_total_branches += len(hits)
#                     for h in hits:
#                         if (h or 0) > 0:
#                             fn_covered_branches += 1

#             # 函数是否命中（是否有任何语句被执行）
#             fn_hit = any(
#                 start <= stmt["start"]["line"] <= end and s.get(sid, 0) > 0
#                 for sid, stmt in statement_map.items()
#             )

#             # 保存函数统计（键为函数名，若同名则覆盖）
#             function_stats[name] = {
#                 "total_lines": len(fn_lines),
#                 "covered_lines": len(fn_covered_lines),
#                 "total_branches": fn_total_branches,
#                 "covered_branches": fn_covered_branches,
#             }

#             # 累加到文件级集合
#             file_lines.update(fn_lines)
#             file_covered_lines.update(fn_covered_lines)
#             file_total_branches += fn_total_branches
#             file_covered_branches += fn_covered_branches

#         # 保存文件统计（键为文件路径）
#         file_stats[file_path] = {
#             "total_lines": len(file_lines),
#             "covered_lines": len(file_covered_lines),
#             "total_branches": file_total_branches,
#             "covered_branches": file_covered_branches,
#         }

#     # 汇总文件级统计
#     file_summary = {
#         "total_lines": 0,
#         "covered_lines": 0,
#         "total_branches": 0,
#         "covered_branches": 0,
#     }
#     for stat in file_stats.values():
#         file_summary["total_lines"] += stat["total_lines"]
#         file_summary["covered_lines"] += stat["covered_lines"]
#         file_summary["total_branches"] += stat["total_branches"]
#         file_summary["covered_branches"] += stat["covered_branches"]

#     # 汇总函数级统计
#     function_summary = {
#         "total_lines": 0,
#         "covered_lines": 0,
#         "total_branches": 0,
#         "covered_branches": 0,
#     }
#     for stat in function_stats.values():
#         function_summary["total_lines"] += stat["total_lines"]
#         function_summary["covered_lines"] += stat["covered_lines"]
#         function_summary["total_branches"] += stat["total_branches"]
#         function_summary["covered_branches"] += stat["covered_branches"]

#     # 构建最终结果
#     result = {
#         "file": file_stats,
#         "function": function_stats,
#         "summary": {
#             "file": file_summary,
#             "function": function_summary,
#         },
#     }

#     # 写入文件
#     output_path = os.path.join(test_result_dir, "cov-summary.json")
#     with open(output_path, "w", encoding="utf-8") as f:
#         json.dump(result, f, indent=2, ensure_ascii=False)

#     return result

# parse_coverage(
#     test_result_dir="test_results/simple-statistics/jest_DSv3.2",
#     coverage_path="test_results/simple-statistics/jest_DSv3.2/coverage/coverage-final.json",
#     data_file_path="data_file.json"
# )
# 可选：保留原 compute_reached_function_metrics 用于其他用途，但本修改中不再调用