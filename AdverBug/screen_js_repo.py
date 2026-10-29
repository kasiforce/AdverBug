"""
screen_js_repo.py —— JavaScript 被测项目两阶段筛选之第二阶段：逐仓库筛查（独立 Jest harness 版）。

与 screen_java_repo.py / screen_py_repo.py 要求一致，差异在生态：
  2. 构建检测：根目录必须有 package.json；不要求项目原生采用 Jest；
  3. 按 lockfile 安装项目依赖，并在缺少 Jest 时临时补装。筛选器创建隔离的
     .adverbug_jest_smoke 目录，只让 Jest 运行其中的测试，逐一动态 import
     候选函数所在源码文件。项目原有 Mocha/node:test/Jasmine 等测试不会执行；
  4. 方法难度阈值（lizard 口径，复用 extract_functions/js_extra.py）：
     调用出度均须 >=5；strict nloc>=100 且 CC>=15，relaxed nloc>=50
     且 CC>=10 补足，标 tier；
  5. 方法级时间过滤（防数据泄露核心）：同前两版，git blame 行日期
     >= cutoff（默认 2026-01-01）。抽取器自带 start_line/end_line，
     直接用于 blame 区间。

输出（schema 与 dataset/simple-statistics.json 等 JS 数据集兼容）：
  <out>/<org>__<repo>.json  候选方法条目（含 nloc/complexity/tier/
                            method_last_modified/repo_meta）
  <out>/summary.csv         每仓库一行；已筛查仓库自动跳过（断点续跑）

需要 node/npm（或 yarn/pnpm）环境；--skip-build 跳过依赖安装与 Jest smoke test
（开发/抽验模式）。node_modules 由包管理器建在仓库内，不污染 git 状态。
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(REPO_ROOT, "extract_functions"), REPO_ROOT,
          os.path.dirname(os.path.abspath(__file__))):
    if p not in sys.path:
        sys.path.insert(0, p)

from js_extra import JSProjectTestScopeExtractor  # noqa: E402
STRICT_MIN_LOC, STRICT_MIN_CC = 100, 15
RELAXED_MIN_LOC, RELAXED_MIN_CC = 50, 10
MIN_OUTGOING_DEGREE = 5

SUMMARY_COLUMNS = [
    "full_name", "sha", "stars", "license", "created_at", "pushed_at",
    "status", "reject_reason", "baseline_seconds", "n_poms", "junit_version",
    "strict_post_cutoff", "relaxed_post_cutoff", "strict_pre_cutoff",
    "relaxed_pre_cutoff", "selected", "screened_at",
]


def sh(cmd, cwd=None, timeout=None, env=None):
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)


def tail_out(proc, limit=400):
    output = (getattr(proc, "stderr", "") or "") + (getattr(proc, "stdout", "") or "")
    return output.strip()[-limit:].replace("\n", " | ")


def find_line_span(file_path, code):
    with open(file_path, encoding="utf-8", errors="ignore") as f:
        lines = f.read().splitlines()
    code_lines = code.splitlines()
    if not code_lines:
        return None
    first = code_lines[0].strip()
    for i, line in enumerate(lines):
        if line.strip() != first:
            continue
        check = range(1, min(4, len(code_lines)))
        if all(i + k < len(lines) and lines[i + k].strip() == code_lines[k].strip()
               for k in check):
            return i + 1, i + len(code_lines)
    return None


_BLAME_CACHE = {}


def blame_line_dates(repo_dir, rel_path, start, end):
    key = (repo_dir, rel_path)
    if key not in _BLAME_CACHE:
        proc = sh(["git", "blame", "--line-porcelain", "--", rel_path],
                  cwd=repo_dir, timeout=600)
        if proc.returncode != 0:
            _BLAME_CACHE[key] = None
        else:
            line_no = 0
            values = {}
            timestamp = None
            for line in proc.stdout.splitlines():
                if line.startswith("committer-time "):
                    timestamp = int(line.split()[1])
                elif line.startswith("\t"):
                    line_no += 1
                    if timestamp is not None:
                        values[line_no] = timestamp
            _BLAME_CACHE[key] = values
    values = _BLAME_CACHE[key]
    if values is None:
        return None
    times = [values[n] for n in range(start, end + 1) if n in values]
    return times or None


def difficulty_tier(method):
    if method.get("outgoing_degree", 0) < MIN_OUTGOING_DEGREE:
        return None
    if method["loc"] >= STRICT_MIN_LOC and method["complexity"] >= STRICT_MIN_CC:
        return "strict"
    if method["loc"] >= RELAXED_MIN_LOC and method["complexity"] >= RELAXED_MIN_CC:
        return "relaxed"
    return None

# 排除的目录/文件：测试、构建产物、示例等非被测源码
EXCLUDE_DIRS = {"__tests__", "__mocks__", "tests", "test", "testing",
                "dist", "build", "coverage", "docs", "doc",
                "examples", "example", "benchmarks", "benchmark", ".storybook"}
SOURCE_EXTS = (".js", ".jsx", ".mjs", ".cjs")
JEST_CONFIG_FILES = ("jest.config.js", "jest.config.ts", "jest.config.cjs",
                     "jest.config.mjs", "jest.config.json")


def is_source_js(rel_path):
    """判断是否为被测源码文件（排除测试/构建产物/示例目录与测试文件命名）。"""
    parts = rel_path.lower().split("/")
    if any(seg in EXCLUDE_DIRS for seg in parts[:-1]):
        return False
    base = parts[-1]
    if not base.endswith(SOURCE_EXTS):
        return False
    return not (".test." in base or ".spec." in base or base.endswith(".config.js"))


def detect_build(repo_dir):
    """返回 {package_json, jest_declared, jest_declared_in, lockfile_mgr}。"""
    pkg_path = os.path.join(repo_dir, "package.json")
    if not os.path.exists(pkg_path):
        return None
    try:
        with open(pkg_path, encoding="utf-8", errors="ignore") as f:
            pkg = json.load(f)
    except json.JSONDecodeError:
        return None

    declared_in = []
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        for dep in (pkg.get(section) or {}):
            if "jest" in dep.lower():
                declared_in.append(f"{section}:{dep}")
    test_script = (pkg.get("scripts") or {}).get("test", "")
    if "jest" in test_script.lower():
        declared_in.append("scripts.test")
    for cfg in JEST_CONFIG_FILES:
        if os.path.exists(os.path.join(repo_dir, cfg)):
            declared_in.append(cfg)
            break

    if os.path.exists(os.path.join(repo_dir, "package-lock.json")):
        mgr = "npm-ci"
    elif os.path.exists(os.path.join(repo_dir, "yarn.lock")):
        mgr = "yarn"
    elif os.path.exists(os.path.join(repo_dir, "pnpm-lock.yaml")):
        mgr = "pnpm"
    else:
        mgr = "npm"
    return {
        "package_json": True,
        "jest_declared": bool(declared_in),
        "jest_declared_in": ",".join(declared_in[:3]),
        "lockfile_mgr": mgr,
    }


def setup_deps(repo_dir, mgr, timeout):
    """按 lockfile 选包管理器安装依赖；确保 jest 可执行。返回 (ok, reason)。"""
    install_env = dict(os.environ)
    # import smoke 不需要浏览器二进制；跳过下载可减少镜像体积并避免 CDN 波动。
    install_env.update({
        "PUPPETEER_SKIP_DOWNLOAD": "1",
        "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
        "CHROMEDRIVER_SKIP_DOWNLOAD": "true",
    })
    if mgr == "yarn" and shutil.which("yarn"):
        cmd = ["yarn", "install", "--frozen-lockfile"]
    elif mgr == "yarn" and shutil.which("corepack"):
        cmd = ["corepack", "yarn", "install", "--frozen-lockfile"]
    elif mgr == "pnpm" and shutil.which("pnpm"):
        cmd = ["pnpm", "install", "--frozen-lockfile"]
    elif mgr == "npm-ci":
        cmd = ["npm", "ci", "--no-audit", "--no-fund"]
    else:
        cmd = ["npm", "install", "--no-audit", "--no-fund"]
    try:
        proc = sh(cmd, cwd=repo_dir, timeout=timeout, env=install_env)
    except subprocess.TimeoutExpired:
        return False, f"{' '.join(cmd[:2])} 超时(>{timeout}s)"
    if proc.returncode != 0 and mgr == "npm-ci":
        # lockfile 与 package.json 不同步时退化为 npm install
        cmd = ["npm", "install", "--no-audit", "--no-fund"]
        try:
            proc = sh(cmd, cwd=repo_dir, timeout=timeout, env=install_env)
        except subprocess.TimeoutExpired:
            return False, f"npm install 超时(>{timeout}s)"
    if proc.returncode != 0:
        return False, f"{' '.join(cmd[:2])} 失败: {tail_out(proc, 300)}"

    # 项目未安装 Jest 时，将 runner 装进隔离 runtime，避免 Jest 的依赖约束
    # 与项目（尤其旧项目）的 package.json / lockfile 冲突。
    if not os.path.exists(os.path.join(repo_dir, "node_modules", ".bin", "jest")):
        runtime_dir = os.path.join(repo_dir, ".adverbug_jest_runtime")
        os.makedirs(runtime_dir, exist_ok=True)
        runtime_package = os.path.join(runtime_dir, "package.json")
        if not os.path.exists(runtime_package):
            with open(runtime_package, "w", encoding="utf-8") as f:
                json.dump({"name": "adverbug-jest-runtime", "private": True}, f)
        try:
            proc = sh(["npm", "install", "--no-save", "--no-audit", "--no-fund", "jest"],
                      cwd=runtime_dir, timeout=timeout, env=install_env)
        except subprocess.TimeoutExpired:
            return False, "补装 jest 超时"
        # npm 的 allow-scripts 策略可能在非 Jest 的可选 postinstall 被拦截时
        # 返回非零；只要 Jest runner 已完整落盘，smoke test 本身就是最终判据。
        if not os.path.exists(os.path.join(
                runtime_dir, "node_modules", ".bin", "jest")):
            return False, f"无法安装隔离 Jest runtime: {tail_out(proc, 300)}"
    return True, ""


def find_jest_binary(repo_dir):
    candidates = (
        os.path.join(repo_dir, "node_modules", ".bin", "jest"),
        os.path.join(repo_dir, ".adverbug_jest_runtime", "node_modules", ".bin", "jest"),
    )
    return next((path for path in candidates if os.path.exists(path)), candidates[0])


def parse_jest_json(path):
    """解析 jest --json 报告，返回 {(fullName): passed|failed|skipped}。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    results = {}
    for suite in data.get("testResults", []):
        for a in suite.get("assertionResults", []):
            status = a.get("status", "passed")
            if status in ("skipped", "pending", "todo"):
                results[a.get("fullName", a.get("title", ""))] = "skipped"
            elif status == "failed":
                results[a.get("fullName", a.get("title", ""))] = "failed"
            else:
                results[a.get("fullName", a.get("title", ""))] = "passed"
    return results


def run_import_smoke(repo_dir, source_files, timeout):
    """用隔离 Jest 配置动态 import 源文件，返回可由生成测试加载的文件集合。"""
    repo_dir = os.path.abspath(repo_dir)
    jest_bin = find_jest_binary(repo_dir)
    smoke_dir = os.path.join(repo_dir, ".adverbug_jest_smoke")
    os.makedirs(smoke_dir, exist_ok=True)
    test_path = os.path.join(smoke_dir, "import-smoke.test.cjs")
    config_path = os.path.join(smoke_dir, "jest.config.cjs")
    report_path = os.path.join(smoke_dir, "report.json")

    # cjs 测试文件 + dynamic import 同时适配 package.json type=module 和 CJS。
    # 测试名采用相对路径，便于从 Jest JSON 精确还原通过的模块。
    cases = []
    for rel in sorted(set(source_files)):
        abs_path = os.path.abspath(os.path.join(repo_dir, rel))
        cases.append(
            "test(" + json.dumps(rel) + ", async () => {\n"
            "  const mod = await import(pathToFileURL(" + json.dumps(abs_path) + ").href);\n"
            "  expect(mod).toBeDefined();\n"
            "});\n"
        )
    with open(test_path, "w", encoding="utf-8") as f:
        f.write("const { pathToFileURL } = require('node:url');\n" + "".join(cases))
    project_babel_jest = os.path.join(repo_dir, "node_modules", "babel-jest")
    runtime_babel_jest = os.path.join(
        repo_dir, ".adverbug_jest_runtime", "node_modules", "babel-jest")
    babel_jest = project_babel_jest if os.path.exists(project_babel_jest) else runtime_babel_jest
    with open(config_path, "w", encoding="utf-8") as f:
        f.write("module.exports = {\n"
                "  testEnvironment: 'node',\n"
                "  testMatch: ['<rootDir>/import-smoke.test.cjs'],\n"
                "  transform: {'^.+\\\\.[jt]sx?$': " + json.dumps(babel_jest) + "},\n"
                "  clearMocks: true,\n"
                "  restoreMocks: true,\n"
                "};\n")

    t0 = time.time()
    try:
        env = dict(os.environ)
        old_opts = env.get("NODE_OPTIONS", "")
        env["NODE_OPTIONS"] = (old_opts + " --experimental-vm-modules").strip()
        proc = subprocess.run(
            [jest_bin, "--config", config_path, "--ci", "--runInBand",
             "--testTimeout=60000", "--json", f"--outputFile={report_path}"],
            cwd=repo_dir, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(smoke_dir, ignore_errors=True)
        return {"ok": False, "reason": f"独立 Jest smoke test 超时(>{timeout}s)"}
    results = parse_jest_json(report_path)
    loadable = {name for name, status in results.items() if status == "passed"}
    reason = ""
    if not results:
        reason = f"独立 Jest smoke test 没有解析到结果: {tail_out(proc, 300)}"
    shutil.rmtree(smoke_dir, ignore_errors=True)
    return {
        "ok": bool(loadable),
        "reason": reason or ("没有候选源码模块可被 Jest import" if not loadable else ""),
        "loadable": loadable,
        "results": results,
        "output_tail": tail_out(proc, 1200),
        "seconds": round(time.time() - t0, 1),
    }


def extract_methods(repo_dir, min_loc_threshold=5):
    """复用 js_extractor 的 tree-sitter 抽取（公有性已内联，无硬规则过滤）。"""
    proc = sh(["git", "ls-files"], cwd=repo_dir, timeout=120)
    if proc.returncode != 0:
        return []
    src_files = [os.path.join(repo_dir, rel) for rel in proc.stdout.splitlines()
                 if rel.lower().endswith(SOURCE_EXTS) and is_source_js(rel)]
    if not src_files:
        return []

    extractor = JSProjectTestScopeExtractor(
        project_root=repo_dir, file_list=src_files,
        min_loc_threshold=min_loc_threshold,
    )
    return extractor._extract_project_functions()


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

        # 2. package.json 检测；项目原生测试框架不限
        build = detect_build(repo_dir)
        if build is None:
            return reject("仓库根无 package.json（非 npm 项目）")
        row["junit_version"] = "jest-independent-harness"

        # 2.5 主代码活跃度快筛
        log_proc = sh(["git", "log", f"--since={args.cutoff}", "--name-only",
                       "--pretty=format:", "--", "*.js", "*.jsx", "*.mjs", "*.cjs"],
                      cwd=repo_dir, timeout=300)
        src_touch = [l for l in log_proc.stdout.splitlines() if is_source_js(l)]
        if not src_touch:
            return reject(f"cutoff {args.cutoff} 以来无源码 js 提交（主代码冻结）")

        # 3. 安装项目依赖；缺少 Jest 时仅向工作 clone 的 node_modules 补装
        if not args.skip_build:
            print(f"[{full}] 安装依赖 ({build['lockfile_mgr']}) ...")
            ok, reason = setup_deps(repo_dir, build["lockfile_mgr"], args.install_timeout)
            if not ok:
                return reject(f"依赖安装失败: {reason}")

        # 4. 方法抽取 + 难度分层
        methods = extract_methods(repo_dir)
        print(f"[{full}] 候选方法（过滤后）: {len(methods)}")
        cutoff = datetime.strptime(args.cutoff, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        blame_failed = 0
        strict, relaxed = [], []
        strict_pre = relaxed_pre = 0
        for m in methods:
            tier = difficulty_tier(m)
            if tier is None or m["name"] == "main":
                continue
            # 5. 方法级时间过滤（防泄露）；js_extractor 自带 start/end line
            rel_path = (m["src_file"] if not os.path.isabs(m["src_file"])
                        else os.path.relpath(m["src_file"], repo_dir)).replace(os.sep, "/")
            start = m.get("start_line")
            end = m.get("end_line")
            if not (start and end):
                span = find_line_span(os.path.join(repo_dir, rel_path), m["code"])
                if span:
                    start, end = span
            dates = blame_line_dates(repo_dir, rel_path, start, end) if start and end else None
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

        # 5. 独立 Jest harness 只 import 候选源码，不发现、不运行项目原测试。
        # 只有 import 成功的源码文件才能进入 benchmark。
        strict.sort(key=lambda m: (-m["complexity"], -m["loc"]))
        relaxed.sort(key=lambda m: (-m["complexity"], -m["loc"]))
        # 给 import 失败留足替补，但避免在超大型仓库中一次启动数百个模块。
        smoke_pool_size = max(args.cap * 5, args.min_required * 5)
        eligible = (strict + relaxed)[:smoke_pool_size]
        if not args.skip_build and eligible:
            rel_files = []
            for m in eligible:
                rel = (m["src_file"] if not os.path.isabs(m["src_file"])
                       else os.path.relpath(m["src_file"], repo_dir)).replace(os.sep, "/")
                rel_files.append(rel)
            smoke = run_import_smoke(repo_dir, rel_files, args.timeout)
            row["baseline_seconds"] = smoke["seconds"]
            if not smoke["ok"]:
                return reject(smoke["reason"])
            strict = [m for m in strict if (m["src_file"] if not os.path.isabs(m["src_file"])
                      else os.path.relpath(m["src_file"], repo_dir)).replace(os.sep, "/")
                      in smoke["loadable"]]
            relaxed = [m for m in relaxed if (m["src_file"] if not os.path.isabs(m["src_file"])
                       else os.path.relpath(m["src_file"], repo_dir)).replace(os.sep, "/")
                       in smoke["loadable"]]
        else:
            row["baseline_seconds"] = "skipped"

        # strict 为主，不足 min-required 用 relaxed 补足
        selected = list(strict)
        if len(selected) < args.min_required:
            selected += relaxed[:args.min_required - len(selected)]
        selected.sort(key=lambda m: (-m["complexity"], -m["loc"]))
        selected = selected[:args.cap]
        row["strict_post_cutoff"] = len(strict)
        row["relaxed_post_cutoff"] = len(relaxed)
        row["selected"] = len(selected)
        if len(selected) < args.min_required:
            return reject(f"过 cutoff 候选不足（strict={len(strict)}, relaxed={len(relaxed)}）")

        # 6. 输出（schema 与 dataset/simple-statistics.json 等 JS 数据集兼容）
        entries = []
        for m in selected:
            entry = {
                "project_root": f"projects/{name}",
                "name": m["name"],
                "src_file": (m["src_file"] if not os.path.isabs(m["src_file"])
                             else os.path.relpath(m["src_file"], repo_dir)).replace(os.sep, "/"),
                "test_file": m.get("test_file", ""),
                "code": m["code"],
                "is_async": m.get("is_async", False),
                "type": m.get("type", "function"),
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
                    "native_jest_declared": build["jest_declared"],
                    "test_harness": "independent-jest-import-smoke",
                    "screened_at": row["screened_at"],
                },
            }
            for k in ("start_line", "end_line", "class_name", "full_class_name",
                      "class_hierarchy", "class_constructor", "class_fields"):
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
# 主流程（与 screen_java_repo.py / screen_py_repo.py 相同的断点续跑逻辑）
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
    parser = argparse.ArgumentParser(
        description="第二阶段（JavaScript/Jest）：逐仓库筛查（package.json → 独立 Jest import smoke → 方法阈值与防泄露过滤）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--csv", default="github_repos_javascript.csv", help="第一阶段输出的仓库 CSV")
    parser.add_argument("--out", default=os.path.join(REPO_ROOT, "dataset", "js_candidates"),
                        help="候选方法 JSON 与 summary.csv 输出目录")
    parser.add_argument("--work-dir", default=os.path.join(REPO_ROOT, "screen_work_js"),
                        help="clone 工作目录")
    parser.add_argument("--cutoff", default="2026-01-01", help="防泄露时间过滤 cutoff（YYYY-MM-DD）")
    parser.add_argument("--recency", choices=["any_line", "all_lines"], default="any_line",
                        help="any_line=max(行日期)>=cutoff；all_lines=min(行日期)>=cutoff")
    parser.add_argument("--limit", type=int, default=None, help="只处理 CSV 前 N 个仓库")
    parser.add_argument("--min-required", type=int, default=5, help="每项目最少候选方法数")
    parser.add_argument("--cap", type=int, default=20, help="每项目最多选用的方法数")
    parser.add_argument("--timeout", type=int, default=1800, help="单遍 Jest 超时（秒）")
    parser.add_argument("--install-timeout", type=int, default=1800, help="依赖安装超时（秒）")
    parser.add_argument("--skip-build", action="store_true",
                        help="跳过依赖安装与独立 Jest smoke test（开发/抽验模式）")
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

    print(f"\n完成。summary: {summary_path}")


if __name__ == "__main__":
    main()
