"""
screen_java_repo.py —— Java 被测项目两阶段筛选之第二阶段：逐仓库筛查。

第一阶段（filter_repo.py）用 GitHub Search API 拿到成熟项目候选
（stars 1000..5000、pushed 2026、Maven 友好的 Java 仓库），本脚本逐仓库：

  1. clone 并固定当前最新 HEAD SHA —— 筛选时点即基准快照，之后所有被测模型
     评测都跑这同一个 SHA（不 checkout 历史标签/旧 commit）；
  2. 构建检测：存在 pom.xml 且任意 pom 声明 junit / jupiter / vintage 依赖
     （下游 pipeline 注入 junit 4.13.2 + vintage engine，提示词要求 JUnit 4；
     Gradle-only 项目如 Java_NFe 在此被拒）；
  3. 基线全绿且稳定：用 eval_java.py 同款 mvn 命令跑两遍，surefire 逐测试
     对比——存在 failed/error 或两遍结果不一致（flaky）→ 拒绝。jedis 这类
     需要外部 Redis 的项目会在此暴露；
  4. 方法难度阈值（lizard 口径，与 gen_test/java_extractor.py 一致）：
       strict  tier: nloc >= 100 且 cyclomatic_complexity >= 15
       relaxed tier: nloc >= 50  且 cyclomatic_complexity >= 10
     strict 过 cutoff 的方法不足 --min-required 个时用 relaxed 补足，
     条目标 tier 字段；每项目最多 --cap 个，按复杂度降序；
  5. 方法级时间过滤（防数据泄露核心）：git blame 取方法内各行的 committer
     时间——--recency any_line 要求 max(行日期) >= cutoff（默认 2026-01-01，
     方法的精确当前形态晚于主流模型训练截止，无法被逐字背诵）；
     all_lines 要求 min(行日期) >= cutoff（仅全新方法，最严格）。
     思路：成熟库 2026 年仍在进新代码，"老库的新代码"兼得库级可测性与
     内容新鲜度（新仓库方案经实测不可行：stars>1000 且 2026 年创建的
     Java 仓库全 GitHub 仅 16 个，且几乎全是应用/平台型项目）。

输出（条目 schema 与 dataset/*.json、hutool_100.json 兼容；多出字段不影响
下游 gen_specification.py → llm_gentests.py → adver_dual.py）：
  <out>/<org>__<repo>.json  候选方法条目（含 nloc/complexity/tier/
                            method_last_modified/repo_meta）
  <out>/summary.csv         每仓库一行：SHA、各层数量、拒绝原因等

断点续跑：summary.csv 中已有的仓库自动跳过。基线构建需要在装有 Maven/JDK
的机器上运行；本机无 mvn 时可用 --skip-build 跳过第 3 步（开发/抽验模式，
summary 中记 baseline=skipped）。
"""

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(REPO_ROOT, "gen_test"), REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from java_extractor import JavaProjectTestScopeExtractor  # noqa: E402
from jacoco_xml import parse_jacoco_xml  # noqa: E402

# 与 eval_java.py 基线完全一致的 mvn 命令（-DforkCount=0 使 surefire 报告
# 在进程内生成，行为与后续评测路径一致）
MVN_BASELINE = (
    "mvn -fae clean org.jacoco:jacoco-maven-plugin:0.8.14:prepare-agent test "
    "org.jacoco:jacoco-maven-plugin:0.8.14:report -DskipTests=false "
    "-Dmaven.test.skip=false -DfailIfNoTests=false "
    "-Dmaven.test.failure.ignore=true -Drat.skip=true -DforkCount=0 -B"
).split()

STRICT_MIN_LOC, STRICT_MIN_CC = 100, 15
RELAXED_MIN_LOC, RELAXED_MIN_CC = 50, 10

SUMMARY_COLUMNS = [
    "full_name", "sha", "stars", "license", "created_at", "pushed_at",
    "status", "reject_reason", "baseline_seconds", "n_poms", "junit_version",
    "strict_post_cutoff", "relaxed_post_cutoff", "strict_pre_cutoff",
    "relaxed_pre_cutoff", "selected", "screened_at",
]


def sh(cmd, cwd=None, timeout=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def tail_out(proc, limit=400):
    text = (proc.stderr or "") + (proc.stdout or "")
    return text.strip()[-limit:].replace("\n", " | ")


# ---------------------------------------------------------------------------
# 基线构建 / surefire / jacoco
# ---------------------------------------------------------------------------

def parse_surefire(repo_dir):
    """解析 surefire XML，返回 {(classname, testname): passed|failed|skipped}。

    语义与 adver_dual.parse_surefire_results 一致，只是以参数指定仓库目录
    （adver_dual 的实现绑定在容器内 /testbed）。
    """
    results = {}
    for base, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d != ".git"]
        if os.path.basename(base) != "surefire-reports":
            continue
        for fn in files:
            if not (fn.startswith("TEST-") and fn.endswith(".xml")):
                continue
            try:
                root = ET.parse(os.path.join(base, fn)).getroot()
            except ET.ParseError:
                continue
            for tc in root.iter("testcase"):
                key = (tc.get("classname", ""), tc.get("name", ""))
                if tc.find("failure") is not None or tc.find("error") is not None:
                    results[key] = "failed"
                elif tc.find("skipped") is not None:
                    results[key] = "skipped"
                else:
                    results[key] = "passed"
    return results


def collect_jacoco(repo_dir):
    out = []
    for base, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d != ".git"]
        if "jacoco.xml" in files:
            out.append(os.path.join(base, "jacoco.xml"))
    return out


def covered_classes(jacoco_files):
    """合并各模块 jacoco.xml，返回被测试触达过的 (类名, 方法名) 键集合及类名集合。"""
    func_keys, class_names = set(), set()
    for path in jacoco_files:
        try:
            cov = parse_jacoco_xml(path)
        except Exception as e:
            print(f"  jacoco 解析失败 {path}: {e}")
            continue
        keys = set(cov.get("function_coverage", {}).keys())  # 形如 "Class.method"
        func_keys |= keys
        class_names |= {k.rsplit(".", 1)[0] for k in keys}
    return func_keys, class_names


def run_baseline(repo_dir, timeout, runs=2):
    """基线 mvn test 跑 runs 遍：必须 0 失败，且每遍 surefire 结果完全一致。"""
    t0 = time.time()
    maps = []
    for i in range(runs):
        try:
            proc = sh(MVN_BASELINE, cwd=repo_dir, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"ok": False, "reason": f"mvn 第{i + 1}遍超时(>{timeout}s)"}
        if proc.returncode != 0:
            return {"ok": False,
                    "reason": f"mvn 第{i + 1}遍失败 rc={proc.returncode}: {tail_out(proc)}"}
        maps.append(parse_surefire(repo_dir))

    failed = [k for k, v in maps[0].items() if v == "failed"]
    if failed:
        return {"ok": False, "reason": f"基线存在 {len(failed)} 个失败用例，例: {failed[:3]}"}
    if not maps[0]:
        return {"ok": False, "reason": "没有解析到任何 surefire 用例（无测试或报告缺失）"}
    if maps[0] != maps[1]:
        diff = [k for k in set(maps[0]) | set(maps[1]) if maps[0].get(k) != maps[1].get(k)]
        return {"ok": False, "reason": f"flaky: 两遍结果不一致，例: {diff[:5]}"}
    return {"ok": True, "results": maps[0], "seconds": round(time.time() - t0, 1)}


# ---------------------------------------------------------------------------
# 方法抽取 + 时间过滤
# ---------------------------------------------------------------------------

def list_tracked_files(repo_dir):
    proc = sh(["git", "ls-files"], cwd=repo_dir, timeout=120)
    if proc.returncode != 0:
        return None
    return proc.stdout.splitlines()


def detect_build(repo_dir):
    """返回 {poms, junit, junit_version, gradle_files}；无 pom 时 poms 为空列表。"""
    files = list_tracked_files(repo_dir)
    if files is None:
        return None
    poms = [f for f in files if os.path.basename(f) == "pom.xml"]
    gradle_files = [f for f in files if f.endswith((".gradle", ".gradle.kts"))]

    junit_version = set()
    for rel in poms:
        try:
            with open(os.path.join(repo_dir, rel), encoding="utf-8", errors="ignore") as f:
                text = f.read().lower()
        except OSError:
            continue
        if re.search(r"<artifactid>junit</artifactid>|junit:junit", text):
            junit_version.add("junit4")
        if "org.junit.jupiter" in text:
            junit_version.add("junit5")
        if "vintage" in text:
            junit_version.add("vintage")
    has_junit = bool(junit_version)
    return {
        "poms": poms,
        "junit": has_junit,
        "junit_version": "+".join(sorted(junit_version)),
        "gradle_files": len(gradle_files),
    }


def extract_methods(repo_dir, min_loc_threshold=5):
    """复用 java_extractor 的 tree-sitter 解析 + 硬规则过滤，但不做分层抽样，
    返回通过过滤的全部方法（内部字段 loc / complexity 为 lizard 口径）。"""
    files = list_tracked_files(repo_dir)
    src_files = [
        os.path.join(repo_dir, rel)
        for rel in files
        if "/src/main/java/" in f"/{rel}" and rel.endswith(".java")
    ]
    if not src_files:
        return []

    extractor = JavaProjectTestScopeExtractor(
        project_root=repo_dir, file_list=src_files,
        min_loc_threshold=min_loc_threshold,
    )
    extractor._parse_project()

    methods = []
    for class_name, cls in extractor.classes.items():
        for m in extractor._compute_test_scope_for_class(class_name):
            m["class_name"] = class_name
            should_filter, _ = extractor._should_filter_method(m)
            if should_filter:
                continue
            m["class_constructor"] = cls.get("constructor_codes", [])
            m["class_fields"] = cls.get("field_codes", [])
            methods.append(m)
    return methods, extractor


def find_line_span(file_path, code):
    """定位方法代码在源文件中的 1-based 行区间 [start, end]。"""
    with open(file_path, encoding="utf-8", errors="ignore") as f:
        lines = f.read().splitlines()
    code_lines = code.splitlines()
    first = code_lines[0].strip()
    for i, line in enumerate(lines):
        if line.strip() != first:
            continue
        # 校验后续几行逐行一致，避免同名签名误匹配
        check = range(1, min(4, len(code_lines)))
        if all(i + k < len(lines)
               and lines[i + k].strip() == code_lines[k].strip()
               for k in check):
            return i + 1, i + len(code_lines)
    return None


# 按 (repo_dir, rel_path) 缓存整文件 blame 结果：--filter=blob:none 部分克隆下
# 每方法一次 blame 会触发逐 blob 网络拉取（jackson-databind 级别的大仓库直接
# 卡死），改为每文件 blame 一次再按行切片，结果与逐段 blame 完全一致
_BLAME_CACHE = {}


def blame_file_times(repo_dir, rel_path):
    """整文件 git blame --porcelain，返回 {行号: committer 时间戳(秒)}；失败返回 None。"""
    proc = sh(["git", "blame", "--porcelain", "--", rel_path], cwd=repo_dir, timeout=600)
    if proc.returncode != 0:
        return None
    sha_time, line_time = {}, {}
    cur_sha = None
    for line in proc.stdout.splitlines():
        if line.startswith("committer-time "):
            if cur_sha:
                sha_time[cur_sha] = int(line.split()[1])
            continue
        if line.startswith("\t") or not line:
            continue
        parts = line.split()
        sha = parts[0].lstrip("^")
        if len(parts) >= 3 and len(sha) == 40 and all(c in "0123456789abcdef" for c in sha):
            cur_sha = sha
            final, count = int(parts[2]), int(parts[3]) if len(parts) > 3 else 1
            for ln in range(final, final + count):
                line_time[ln] = sha  # 先记 sha，时间在下一轮统一替换
    # 第二遍把行号→sha 替换为行号→时间（短格式行复用同 sha 的时间）
    return {ln: sha_time.get(s) for ln, s in line_time.items() if sha_time.get(s) is not None}


def blame_line_dates(repo_dir, rel_path, start, end):
    """git blame 取 [start, end] 行的 committer 时间戳列表（秒），按文件缓存。"""
    key = (repo_dir, rel_path)
    if key not in _BLAME_CACHE:
        _BLAME_CACHE[key] = blame_file_times(repo_dir, rel_path)
    by_line = _BLAME_CACHE[key]
    if by_line is None:
        return None
    times = [by_line[ln] for ln in range(start, end + 1) if ln in by_line]
    return times or None


def difficulty_tier(m):
    if m["loc"] >= STRICT_MIN_LOC and m["complexity"] >= STRICT_MIN_CC:
        return "strict"
    if m["loc"] >= RELAXED_MIN_LOC and m["complexity"] >= RELAXED_MIN_CC:
        return "relaxed"
    return None


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
    _BLAME_CACHE.clear()
    try:
        # 1. clone + 固定当前最新 HEAD（CSV 中带 local_path 列时从本地路径 clone，
        #    供测试/离线复跑使用；正式筛选走 GitHub）
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

        # 2. Maven + JUnit 检测
        build = detect_build(repo_dir)
        if build is None:
            return reject("git ls-files 失败")
        row["n_poms"] = len(build["poms"])
        row["junit_version"] = build["junit_version"]
        if not build["poms"]:
            return reject(f"无 pom.xml（Gradle-only? gradle文件数={build['gradle_files']}）")
        if not build["junit"]:
            return reject("pom 中未声明 JUnit 依赖")

        # 2.5 主代码活跃度快筛：cutoff 以来 src/main/java 零提交的仓库直接拒绝
        #     （"老库的新代码"策略的前提；同时省掉冻结仓库的基线构建开销）
        log_proc = sh(["git", "log", f"--since={args.cutoff}", "--name-only",
                       "--pretty=format:", "--", "*.java"], cwd=repo_dir, timeout=300)
        main_touch = [l for l in log_proc.stdout.splitlines() if "/src/main/java/" in f"/{l}"]
        if not main_touch:
            return reject(f"cutoff {args.cutoff} 以来 src/main/java 零提交（主代码冻结）")

        # 3. 基线全绿且稳定
        if args.skip_build:
            row["baseline_seconds"] = "skipped"
        else:
            baseline = run_baseline(repo_dir, args.timeout)
            if not baseline["ok"]:
                return reject(baseline["reason"])
            row["baseline_seconds"] = baseline["seconds"]

        # 基线 jacoco → 类被测试触达集合（可测性信号；--skip-build 时为 None）
        covered_func_keys, covered_classes_set = (None, None)
        if not args.skip_build:
            jacoco_files = collect_jacoco(repo_dir)
            if jacoco_files:
                covered_func_keys, covered_classes_set = covered_classes(jacoco_files)

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
            rel_path = os.path.relpath(m["src_file"], repo_dir).replace(os.sep, "/")
            span = find_line_span(m["src_file"], m["code"])
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
            if covered_classes_set is not None:
                m["class_covered_in_baseline"] = m["class_name"] in covered_classes_set
                if not m["class_covered_in_baseline"]:
                    continue  # 类从未被任何测试加载，生成测试大概率测不了
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

        # 6. 输出（schema 与现有数据集兼容 + 防泄露/难度元数据）
        entries = []
        for m in selected:
            entries.append({
                "project_root": f"projects/{name}",
                "name": m["name"],
                "src_file": os.path.relpath(m["src_file"], repo_dir).replace(os.sep, "/"),
                "test_file": extractor._gen_test_file_path(m["src_file"], m["name"]),
                "code": m["code"],
                "is_async": m.get("is_async", False),
                "type": m.get("type", "method"),
                "class_name": m.get("class_name"),
                "full_class_name": m.get("full_class_name"),
                "class_constructor": m.get("class_constructor", []),
                "class_fields": m.get("class_fields", []),
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
            })
        row["status"], row["reject_reason"] = "accepted", ""
        print(f"[{full}] 接受: strict={len(strict)} relaxed={len(relaxed)} 选用={len(selected)}")
        return entries, row
    finally:
        if not args.keep_clones and os.path.isdir(repo_dir):
            shutil.rmtree(repo_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def load_repo_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_done_repos(summary_path):
    if not os.path.exists(summary_path):
        return set()
    with open(summary_path, newline="", encoding="utf-8") as f:
        # error 行（磁盘满等瞬时错误）不视为已完成，下次运行重试；
        # 同一仓库可能出现多行（重试），分析时取最后一行
        return {r["full_name"] for r in csv.DictReader(f) if r["status"] != "error"}


def append_summary(summary_path, row):
    new_file = not os.path.exists(summary_path)
    with open(summary_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(
        description="第二阶段：逐仓库筛查（Maven+JUnit → 基线全绿 → 方法阈值 → 方法级防泄露时间过滤）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--csv", default="github_repos_java.csv", help="第一阶段输出的仓库 CSV")
    parser.add_argument("--out", default=os.path.join(REPO_ROOT, "dataset", "java_candidates"),
                        help="候选方法 JSON 与 summary.csv 输出目录")
    parser.add_argument("--work-dir", default=os.path.join(REPO_ROOT, "screen_work"),
                        help="clone 工作目录")
    parser.add_argument("--cutoff", default="2026-01-01", help="防泄露时间过滤 cutoff（YYYY-MM-DD）")
    parser.add_argument("--recency", choices=["any_line", "all_lines"], default="any_line",
                        help="any_line=max(行日期)>=cutoff；all_lines=min(行日期)>=cutoff")
    parser.add_argument("--limit", type=int, default=None, help="只处理 CSV 前 N 个仓库")
    parser.add_argument("--min-required", type=int, default=5, help="每项目最少候选方法数")
    parser.add_argument("--cap", type=int, default=20, help="每项目最多选用的方法数")
    parser.add_argument("--timeout", type=int, default=1800, help="单遍基线 mvn 超时（秒）")
    parser.add_argument("--skip-build", action="store_true",
                        help="跳过基线 mvn 构建（本机无 Maven 时的开发/抽验模式）")
    parser.add_argument("--keep-clones", action="store_true", help="筛查后保留 clone（便于换 cutoff 重跑）")
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

    accepted = load_done_repos(summary_path)
    print(f"\n完成。summary: {summary_path}")


if __name__ == "__main__":
    main()
