"""
screen_py_repo.py —— Python 被测项目两阶段筛选之第二阶段：逐仓库筛查（pytest 版）。

与 screen_java_repo.py（Java/maven/junit4 版）要求一致，差异在生态：
  2. 构建检测：存在 pyproject.toml / setup.py / setup.cfg，且 pytest 在
     pyproject.toml / setup.cfg / setup.py / tox.ini / requirements*.txt
     中声明（下游 eval_py.py 用 pytest 跑生成的测试）；
  3. 基线全绿且稳定：为仓库建独立 venv（python -m venv + pip install -e . +
     pytest/coverage/pytest-timeout），用 eval_py.py 同款风格的
     `python -m pytest --import-mode=importlib --continue-on-collection-errors`
     跑两遍，junitxml 逐测试对比——有 failed/error 或两遍不一致（flaky）→ 拒绝；
     第一遍套 coverage（eval 同款）取文件级覆盖，作为可测性信号；
  4. 方法难度阈值（lizard 口径，复用 gen_test/py_extractor.py）：
     strict nloc>=100 且 CC>=15，relaxed nloc>=50 且 CC>=10 补足，标 tier；
  5. 方法级时间过滤（防数据泄露核心）：同 Java 版，git blame 行日期
     >= cutoff（默认 2026-01-01）。

输出（schema 与 dataset/flask.json 等 Python 数据集兼容）：
  <out>/<org>__<repo>.json  候选方法条目（含 nloc/complexity/tier/
                            method_last_modified/repo_meta）
  <out>/summary.csv         每仓库一行；已筛查仓库自动跳过（断点续跑）

基线 venv + pytest 在装有 python3 的机器即可运行（比 Java 版要求低）；
--skip-build 跳过 venv/pytest（开发/抽验模式）。venv 与临时产物建在仓库
目录内（.venv-screen / .screen_*），不污染 git 状态。
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(REPO_ROOT, "gen_test"), REPO_ROOT, os.path.dirname(os.path.abspath(__file__))):
    if p not in sys.path:
        sys.path.insert(0, p)

from py_extractor import EnhancedPythonFocalExtractor  # noqa: E402
# 与 Java 版共享：通用工具、行定位、blame、难度阈值、summary 列
from screen_java_repo import (  # noqa: E402
    SUMMARY_COLUMNS, difficulty_tier, blame_line_dates, find_line_span, sh, tail_out,
)

# 排除的目录/文件：测试、文档、示例等非被测源码
EXCLUDE_DIRS = {"tests", "test", "testing", "docs", "doc", "examples", "example",
                "benchmarks", "build", "dist", "venv", ".venv", "scripts"}
# 打包与测试框架声明文件
PACKAGING_FILES = ("pyproject.toml", "setup.py", "setup.cfg")
PYTEST_DECL_FILES = ("pyproject.toml", "setup.cfg", "setup.py", "tox.ini")


def parse_junit_xml(path):
    """解析 pytest junitxml，返回 {(classname, testname): passed|failed|skipped}。

    testcase 元素结构与 surefire 一致，语义对齐 adver_dual.parse_surefire_results。
    """
    results = {}
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        # 文件不存在（pytest 启动即崩没写出 junitxml）或格式损坏 → 视为无用例
        return results
    for tc in root.iter("testcase"):
        key = (tc.get("classname", ""), tc.get("name", ""))
        if tc.find("failure") is not None or tc.find("error") is not None:
            results[key] = "failed"
        elif tc.find("skipped") is not None:
            results[key] = "skipped"
        else:
            results[key] = "passed"
    return results


def is_source_py(rel_path):
    """判断是否为被测源码文件（排除测试/文档/示例目录与测试文件命名）。"""
    parts = rel_path.lower().split("/")
    if any(seg in EXCLUDE_DIRS for seg in parts[:-1]):
        return False
    base = parts[-1]
    if base in ("setup.py", "conftest.py") or not base.endswith(".py"):
        return False
    return not (base.startswith("test_") or base.endswith("_test.py"))


def detect_build(repo_dir):
    """返回 {packaging, pytest_declared, pytest_declared_in}。"""
    proc = sh(["git", "ls-files"], cwd=repo_dir, timeout=120)
    if proc.returncode != 0:
        return None
    files = proc.stdout.splitlines()

    packaging = [f for f in files
                 if "/" not in f and f in PACKAGING_FILES]  # 仓库根目录的打包文件
    pytest_declared_in = []
    for f in files:
        base = os.path.basename(f)
        # 根目录的声明文件（含 *requirements*.txt）或 CI workflow 中的 pytest
        is_root_decl = "/" not in f and (base in PYTEST_DECL_FILES or "requirements" in base)
        is_ci_wf = f.startswith(".github/workflows/") and f.endswith((".yml", ".yaml"))
        if not (is_root_decl or is_ci_wf):
            continue
        try:
            with open(os.path.join(repo_dir, f), encoding="utf-8", errors="ignore") as fh:
                if "pytest" in fh.read().lower():
                    pytest_declared_in.append(f)
        except OSError:
            continue
    return {
        "packaging": packaging,
        "pytest_declared": bool(pytest_declared_in),
        "pytest_declared_in": ",".join(pytest_declared_in[:3]),
    }


def setup_venv(repo_dir, python_bin, timeout):
    """建 venv 并安装项目 + pytest 工具链。返回 (ok, reason)。"""
    venv_dir = os.path.join(repo_dir, ".venv-screen")
    pip = os.path.join(venv_dir, "bin", "pip")
    steps = [
        [python_bin, "-m", "venv", venv_dir],
        [pip, "install", "--quiet", "--upgrade", "pip"],
        [pip, "install", "--quiet", "-e", "."],
        # 插件集合与 eval_py.py 容器内 pip install 完全一致：eval 不覆盖项目
        # addopts，addopts 依赖额外插件（--cov/-n 等）的项目在 eval 也会挂，
        # 应在筛查阶段就拒绝；缺 pytest-asyncio/pytest-mock 则会误杀异步项目
        [pip, "install", "--quiet", "pytest", "pytest-json-report", "pytest-timeout",
         "coverage", "pytest-asyncio", "pytest-mock", "pycares"],
    ]
    for cmd in steps:
        try:
            proc = sh(cmd, cwd=repo_dir, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, f"{' '.join(cmd[:3])} 超时(>{timeout}s)"
        if proc.returncode != 0:
            return False, f"{' '.join(cmd[:3])} 失败: {tail_out(proc, 300)}"

    # 尽力安装根目录的 *requirements*.txt（如 funcy 的 test_requirements.txt
    # 里的 whatever 等测试专用依赖）。失败不阻断（其中可能有旧版本 pin 装不上），
    # 放在工具链之后装以尊重项目自己的 pin；环境是否可用由基线测试兜底检验。
    for fname in sorted(os.listdir(repo_dir)):
        if fname.endswith(".txt") and "requirement" in fname.lower():
            try:
                sh([pip, "install", "--quiet", "-r", fname],
                   cwd=repo_dir, timeout=timeout)
            except subprocess.TimeoutExpired:
                pass
    return True, ""


def run_baseline(repo_dir, python_bin, timeout, runs=2):
    """pytest 跑 runs 遍：必须 0 失败、>0 用例、每遍结果完全一致。

    第一遍套 coverage（eval_py.py 同款 --omit 口径），产物留在仓库目录。
    """
    venv_bin = os.path.join(repo_dir, ".venv-screen", "bin")
    junit1 = os.path.join(repo_dir, ".screen_junit1.xml")
    junit2 = os.path.join(repo_dir, ".screen_junit2.xml")
    pytest_args = [
        "-m", "pytest",
        # 不用 eval_py.py 的 --import-mode=importlib：prepend（pytest 默认）会把
        # 测试目录加进 sys.path，funcy 这类依赖测试目录内相对导入的项目才能跑
        "--continue-on-collection-errors",
        "--timeout=60",
        "-q", "--disable-warnings", "--tb=no",
    ]
    t0 = time.time()

    # 第一遍：coverage run 包裹（取文件级覆盖作可测性信号）
    try:
        proc = sh([os.path.join(venv_bin, "coverage"), "run", "--branch",
                   "--omit=test_*.py,*_test.py,*/tests/*,*/test/*,*/.venv*",
                   *pytest_args, f"--junitxml={junit1}"],
                  cwd=repo_dir, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": f"pytest 第1遍超时(>{timeout}s)"}
    # coverage 遇到收集失败也会非 0；用 junitxml 内容判定而不是退出码
    map1 = parse_junit_xml(junit1)
    if not map1:
        return {"ok": False, "reason": f"第1遍没有解析到任何测试用例: {tail_out(proc, 300)}"}
    sh([os.path.join(venv_bin, "coverage"), "json", "-o",
        os.path.join(repo_dir, ".screen_coverage.json")], cwd=repo_dir, timeout=300)

    # 第二遍：裸 pytest，验证稳定性
    try:
        proc = sh([os.path.join(venv_bin, "python"), *pytest_args, f"--junitxml={junit2}"],
                  cwd=repo_dir, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": f"pytest 第2遍超时(>{timeout}s)"}
    map2 = parse_junit_xml(junit2)

    failed = [k for k, v in map1.items() if v == "failed"]
    if failed:
        return {"ok": False, "reason": f"基线存在 {len(failed)} 个失败用例，例: {failed[:3]}"}
    if map1 != map2:
        diff = [k for k in set(map1) | set(map2) if map1.get(k) != map2.get(k)]
        return {"ok": False, "reason": f"flaky: 两遍结果不一致，例: {diff[:5]}"}
    return {"ok": True, "results": map1, "seconds": round(time.time() - t0, 1)}


def covered_files(repo_dir):
    """从 coverage json 取有执行行的文件集合（相对 repo_dir 的 posix 路径）。"""
    path = os.path.join(repo_dir, ".screen_coverage.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    covered = set()
    for key, info in data.get("files", {}).items():
        if not info.get("executed_lines"):
            continue
        rel = os.path.relpath(key, repo_dir) if os.path.isabs(key) else key
        covered.add(rel.replace(os.sep, "/"))
    return covered


def extract_methods(repo_dir, min_loc_threshold=5):
    """复用 py_extractor 的 tree-sitter 抽取 + 硬规则过滤，不做分层抽样。"""
    proc = sh(["git", "ls-files"], cwd=repo_dir, timeout=120)
    if proc.returncode != 0:
        return [], None
    src_files = [os.path.join(repo_dir, rel) for rel in proc.stdout.splitlines()
                 if rel.endswith(".py") and is_source_py(rel)]
    if not src_files:
        return [], None

    extractor = EnhancedPythonFocalExtractor(
        project_root=repo_dir, file_list=src_files,
        output_file=os.path.join(repo_dir, ".screen_extract.json"),
        min_loc_threshold=min_loc_threshold,
    )
    methods = []
    for fp in src_files:
        try:
            for m in extractor._extract_focal_method(fp):
                if m.get("name", "").startswith("_"):
                    continue  # 与 extract_and_select_functions 的公有方法过滤一致
                should_filter, _ = extractor._should_filter_method(m)
                if should_filter:
                    continue
                methods.append(m)
        except Exception as e:
            print(f"  抽取失败 {fp}: {str(e)[:80]}")
    return methods, extractor


def screen_repo(meta, args):
    """筛查单个仓库。返回 (entries 或 None, summary_row)。"""
    full = meta["full_name"]
    name = full.split("/")[-1]
    row = {c: "" for c in SUMMARY_COLUMNS}
    row.update({
        "full_name": full,
        "stars": meta.get("stargazers_count", ""),
        "license": meta.get("license", ""),
        "created_at": meta.get("created_at", ""),
        "pushed_at": meta.get("pushed_at", ""),
        "screened_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    def reject(reason):
        row["status"], row["reject_reason"] = "rejected", reason
        print(f"[{full}] 拒绝: {reason}")
        return None, row

    repo_dir = os.path.join(args.work_dir, name)
    try:
        # 1. clone + 固定当前最新 HEAD（local_path 列供本地测试/离线复跑）
        clone_src = meta.get("local_path") or f"https://github.com/{full}.git"
        if not os.path.isdir(os.path.join(repo_dir, ".git")):
            print(f"[{full}] clone <- {clone_src}")
            try:
                proc = sh(["git", "clone", "--quiet", "--filter=blob:none",
                           clone_src, repo_dir], timeout=900)
            except subprocess.TimeoutExpired:
                return reject("clone 超时")
            if proc.returncode != 0:
                return reject(f"clone 失败: {tail_out(proc, 200)}")
        sha_proc = sh(["git", "rev-parse", "HEAD"], cwd=repo_dir)
        if sha_proc.returncode != 0:
            return reject("git rev-parse 失败")
        sha = sha_proc.stdout.strip()
        row["sha"] = sha

        # 2. 打包 + pytest 声明检测
        build = detect_build(repo_dir)
        if build is None:
            return reject("git ls-files 失败")
        if not build["packaging"]:
            return reject("仓库根无 pyproject.toml/setup.py/setup.cfg（非 pip 可安装项目）")
        row["junit_version"] = "pytest"
        if not build["pytest_declared"]:
            return reject("未声明 pytest 依赖")

        # 2.5 主代码活跃度快筛：cutoff 以来无源码提交 → 直接拒绝
        log_proc = sh(["git", "log", f"--since={args.cutoff}", "--name-only",
                       "--pretty=format:", "--", "*.py"], cwd=repo_dir, timeout=300)
        src_touch = [l for l in log_proc.stdout.splitlines() if is_source_py(l)]
        if not src_touch:
            return reject(f"cutoff {args.cutoff} 以来无源码 .py 提交（主代码冻结）")

        # 3. venv + 基线全绿且稳定
        if not args.skip_build:
            print(f"[{full}] venv + pip install -e . ...")
            ok, reason = setup_venv(repo_dir, args.python_bin, args.install_timeout)
            if not ok:
                return reject(f"环境安装失败: {reason}")
            baseline = run_baseline(repo_dir, args.python_bin, args.timeout)
            if not baseline["ok"]:
                return reject(baseline["reason"])
            row["baseline_seconds"] = baseline["seconds"]
        else:
            row["baseline_seconds"] = "skipped"

        covered = covered_files(repo_dir) if not args.skip_build else None

        # 4. 方法抽取 + 难度分层
        methods, extractor = extract_methods(repo_dir)
        print(f"[{full}] 候选方法（过滤后）: {len(methods)}")
        cutoff = datetime.strptime(args.cutoff, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        blame_failed = 0
        strict, relaxed = [], []
        strict_pre = relaxed_pre = 0
        for m in methods:
            tier = difficulty_tier(m)
            if tier is None or m["name"] == "main":
                continue
            # 5. 方法级时间过滤（防泄露）
            # py_extractor 返回的 src_file 是相对 project_root 的路径
            if os.path.isabs(m["src_file"]):
                rel_path = os.path.relpath(m["src_file"], repo_dir).replace(os.sep, "/")
                abs_src = m["src_file"]
            else:
                rel_path = m["src_file"].replace(os.sep, "/")
                abs_src = os.path.join(repo_dir, m["src_file"])
            m["_rel_path"] = rel_path
            span = find_line_span(abs_src, m["code"])
            dates = blame_line_dates(repo_dir, rel_path, *span) if span else None
            if not dates:
                blame_failed += 1
                continue
            max_date = datetime.fromtimestamp(max(dates), tz=timezone.utc)
            min_date = datetime.fromtimestamp(min(dates), tz=timezone.utc)
            ok = (max_date >= cutoff) if args.recency == "any_line" else (min_date >= cutoff)
            if not ok:
                if tier == "strict":
                    strict_pre += 1
                else:
                    relaxed_pre += 1
                continue
            if covered is not None:
                m["class_covered_in_baseline"] = rel_path in covered
                if not m["class_covered_in_baseline"]:
                    continue  # 基线测试从未执行到该文件，生成测试大概率测不了
            else:
                m["class_covered_in_baseline"] = None
            m["tier"] = tier
            m["method_last_modified"] = max_date.strftime("%Y-%m-%d")
            m["method_oldest_line"] = min_date.strftime("%Y-%m-%d")
            (strict if tier == "strict" else relaxed).append(m)

        row.update({
            "strict_post_cutoff": len(strict),
            "relaxed_post_cutoff": len(relaxed),
            "strict_pre_cutoff": strict_pre,
            "relaxed_pre_cutoff": relaxed_pre,
        })
        if blame_failed:
            print(f"[{full}] {blame_failed} 个方法 blame 失败被跳过")

        # strict 为主，不足 min-required 用 relaxed 补足
        selected = list(strict)
        if len(selected) < args.min_required:
            selected += relaxed[:args.min_required - len(selected)]
        selected.sort(key=lambda m: (-m["complexity"], -m["loc"]))
        selected = selected[:args.cap]
        row["selected"] = len(selected)
        if len(selected) < args.min_required:
            return reject(f"过 cutoff 候选不足（strict={len(strict)}, relaxed={len(relaxed)}）")

        # 6. 输出（schema 与 dataset/flask.json 等 Python 数据集兼容）
        # 被测函数所在源文件的 import 上下文（生成测试时需要同样的依赖），按文件缓存
        imports_cache = {}
        entries = []
        for m in selected:
            if m["_rel_path"] not in imports_cache:
                try:
                    imports_cache[m["_rel_path"]] = extractor.extract_file_imports(
                        os.path.join(repo_dir, m["_rel_path"]))
                except Exception as e:
                    print(f"  import 提取失败 {m['_rel_path']}: {str(e)[:80]}")
                    imports_cache[m["_rel_path"]] = {
                        "imports": [], "from_imports": [], "imports_with_aliases": []}
            entry = {
                "project_root": f"projects/{name}",
                "name": m["name"],
                "src_file": m["_rel_path"],
                "test_file": m.get("test_file") or extractor._gen_test_file_path(
                    m["src_file"], m["name"]),
                "code": m["code"],
                "imports": imports_cache[m["_rel_path"]],
                "is_async": m.get("is_async", False),
                "type": m.get("type", "method"),
                "nloc": m["loc"],
                "complexity": m["complexity"],
                "param_count": m.get("param_count", 0),
                "tier": m["tier"],
                "method_last_modified": m["method_last_modified"],
                "method_oldest_line": m["method_oldest_line"],
                "class_covered_in_baseline": m["class_covered_in_baseline"],
                "repo_meta": {
                    "full_name": full,
                    "html_url": meta.get("html_url", ""),
                    "stars": meta.get("stargazers_count", ""),
                    "license": meta.get("license", ""),
                    "created_at": meta.get("created_at", ""),
                    "pushed_at": meta.get("pushed_at", ""),
                    "sha": sha,
                    "cutoff": args.cutoff,
                    "recency": args.recency,
                    "screened_at": row["screened_at"],
                },
            }
            for k in ("class_name", "full_class_name", "class_hierarchy",
                      "class_constructor", "class_fields", "class_variables"):
                if m.get(k) is not None:
                    entry[k] = m[k]
            entries.append(entry)
        row["status"], row["reject_reason"] = "accepted", ""
        print(f"[{full}] 接受: strict={len(strict)} relaxed={len(relaxed)} 选用={len(selected)}")
        return entries, row
    finally:
        if not args.keep_clones and os.path.isdir(repo_dir):
            shutil.rmtree(repo_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 主流程（与 screen_java_repo.py 相同的断点续跑逻辑）
# ---------------------------------------------------------------------------

def load_repo_csv(path):
    import csv
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_done_repos(summary_path):
    import csv
    if not os.path.exists(summary_path):
        return set()
    with open(summary_path, newline="", encoding="utf-8") as f:
        # error 行（磁盘满等瞬时错误）不视为已完成，下次运行重试；
        # 同一仓库可能出现多行（重试），分析时取最后一行
        return {r["full_name"] for r in csv.DictReader(f) if r["status"] != "error"}


def append_summary(summary_path, row):
    import csv
    new_file = not os.path.exists(summary_path)
    with open(summary_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="第二阶段（Python/pytest）：逐仓库筛查（打包+pytest → 基线全绿 → 方法阈值 → 方法级防泄露时间过滤）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--csv", default="github_repos_python.csv", help="第一阶段输出的仓库 CSV")
    parser.add_argument("--out", default=os.path.join(REPO_ROOT, "dataset", "py_candidates"),
                        help="候选方法 JSON 与 summary.csv 输出目录")
    parser.add_argument("--work-dir", default=os.path.join(REPO_ROOT, "screen_work_py"),
                        help="clone 工作目录")
    parser.add_argument("--cutoff", default="2026-01-01", help="防泄露时间过滤 cutoff（YYYY-MM-DD）")
    parser.add_argument("--recency", choices=["any_line", "all_lines"], default="any_line",
                        help="any_line=max(行日期)>=cutoff；all_lines=min(行日期)>=cutoff")
    parser.add_argument("--limit", type=int, default=None, help="只处理 CSV 前 N 个仓库")
    parser.add_argument("--min-required", type=int, default=5, help="每项目最少候选方法数")
    parser.add_argument("--cap", type=int, default=20, help="每项目最多选用的方法数")
    parser.add_argument("--target-accepted", type=int, default=None,
                        help="筛够 N 个 accepted 仓库即停止（默认筛完整个 CSV）")
    parser.add_argument("--timeout", type=int, default=1800, help="单遍 pytest 超时（秒）")
    parser.add_argument("--install-timeout", type=int, default=900, help="venv/pip 安装超时（秒）")
    parser.add_argument("--python-bin", default=sys.executable or "python3",
                        help="建 venv 用的 python 解释器")
    parser.add_argument("--skip-build", action="store_true",
                        help="跳过 venv/pytest 基线（开发/抽验模式）")
    parser.add_argument("--keep-clones", action="store_true", help="筛查后保留 clone")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    os.makedirs(args.work_dir, exist_ok=True)
    summary_path = os.path.join(args.out, "summary.csv")
    done = load_done_repos(summary_path)

    repos = load_repo_csv(args.csv)
    if args.limit:
        repos = repos[:args.limit]
    print(f"待筛查 {len(repos)} 个仓库（已完成跳过 {len([r for r in repos if r['full_name'] in done])} 个），"
          f"cutoff={args.cutoff} recency={args.recency} skip_build={args.skip_build}\n")

    accepted = 0
    for meta in repos:
        if meta["full_name"] in done:
            continue
        try:
            entries, row = screen_repo(meta, args)
        except Exception as e:
            row = {c: "" for c in SUMMARY_COLUMNS}
            row.update({"full_name": meta["full_name"], "status": "error",
                        "reject_reason": f"{type(e).__name__}: {e}",
                        "screened_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
            entries = None
            print(f"[{meta['full_name']}] 异常: {e}")
        append_summary(summary_path, row)
        if entries:
            out_json = os.path.join(args.out, row["full_name"].replace("/", "__") + ".json")
            with open(out_json, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2, ensure_ascii=False)
            accepted += 1
            if args.target_accepted and accepted >= args.target_accepted:
                print(f"\n已达 --target-accepted={args.target_accepted}，停止后续筛查。")
                break

    print(f"\n完成。summary: {summary_path}")


if __name__ == "__main__":
    main()
