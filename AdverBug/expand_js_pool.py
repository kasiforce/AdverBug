"""expand_js_pool.py —— 扩充 JavaScript 一阶段候选池。

背景：filter_repo.py 的搜索条件没有测试框架维度，捞回的仓库 85% 死在
screen_js_repo.py 的"未声明 Jest"/无测试快筛上。本脚本复用同一套硬条件
（stars/pushed/size/language/license），新增 **Jest 声明预过滤**：

  1. Search API 抓 stars:1000..5000 与 stars:300..1000 两个 band（每 band
     受 1000 条上限约束，靠分页拿全）；
  2. 客户端 license 过滤（同 filter_repo.py：apache-2.0 / mit / bsd-3-clause）；
  3. raw.githubusercontent 探测根 package.json：任一 deps 段含 jest、或
     scripts.test 含 jest → 保留；否则再探测 jest.config.* 是否存在；
  4. 与已筛查的 623 个仓库去重（已判定过的不再进池）；
  5. 输出 github_repos_javascript_expanded.csv（schema 同 filter_repo）。

无需 GitHub Token（Search 匿名 10 次/分，已做限速处理）。
"""

import csv
import json
import time
import urllib.parse
import urllib.request
import concurrent.futures as cf

BASE = "https://api.github.com/search/repositories"
RAW = "https://raw.githubusercontent.com/{full}/HEAD/{path}"
ALLOWED_LICENSES = {"apache-2.0", "mit", "bsd-3-clause", "isc"}  # ISC 与 MIT 等价宽松
# 拆细 band 以规避 Search API 每查询 1000 条截断
BANDS = ["stars:1000..1352"]  # 1000..5000 段从未抓取的尾部（原始池 min=1353）
COMMON = ("pushed:2026-01-01..2026-12-31 size:1024..102400 language:JavaScript "
          "fork:false archived:false -topic:android")
JEST_CONFIGS = ["jest.config.js", "jest.config.ts", "jest.config.cjs",
                "jest.config.mjs", "jest.config.json"]
OUT = "AdverBug/github_repos_javascript_expanded3.csv"
SUMMARY = "dataset/js_candidates/summary.csv"


def api_get(url):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "pool-expander",
    })
    return urllib.request.urlopen(req, timeout=30)


def search_band(band):
    """抓一个 band 的全部结果（1000 条上限内），处理匿名限速。"""
    repos, page = [], 1
    while True:
        q = urllib.parse.quote(f"{band} {COMMON}")
        url = f"{BASE}?q={q}&per_page=100&page={page}&sort=stars&order=desc"
        try:
            resp = api_get(url)
        except urllib.error.HTTPError as e:
            if e.code == 403:  # 匿名 10 次/分，等重置
                wait = int(e.headers.get("X-RateLimit-Reset", time.time() + 60)) - time.time() + 1
                print(f"  限速，等待 {wait:.0f}s ...")
                time.sleep(max(wait, 5))
                continue
            raise
        data = json.load(resp)
        items = data.get("items", [])
        repos.extend(items)
        total = data.get("total_count", 0)
        print(f"  [{band}] page {page}: +{len(items)} (累计 {len(repos)}/{min(total, 1000)})")
        if not items or len(repos) >= min(total, 1000):
            return repos, total
        page += 1
        time.sleep(7)  # 匿名 10 req/min → 6s+ 间隔


def fetch_raw(full, path):
    try:
        with urllib.request.urlopen(RAW.format(full=full, path=path), timeout=15) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception:
        return None


def jest_declared(full):
    """与 screen_js_repo.detect_build 同口径的远程探测。返回 (bool, note)。"""
    text = fetch_raw(full, "package.json")
    if text is None:
        return False, "no-package-json"
    try:
        pkg = json.loads(text)
    except json.JSONDecodeError:
        return False, "bad-package-json"
    deps = {}
    for sec in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        deps.update(pkg.get(sec) or {})
    if any("jest" in d.lower() for d in deps):
        return True, "deps"
    if "jest" in ((pkg.get("scripts") or {}).get("test", "") or "").lower():
        return True, "scripts.test"
    for cfg in JEST_CONFIGS:
        if fetch_raw(full, cfg) is not None:
            return True, cfg
    return False, "no-jest"


def main():
    seen = set()
    pool = []
    for band in BANDS:
        repos, total = search_band(band)
        print(f"band {band}: total_count={total}（>1000 时 API 截断到前 1000）")
        for r in repos:
            if r["full_name"] in seen:
                continue
            seen.add(r["full_name"])
            pool.append(r)

    before = len(pool)
    pool = [r for r in pool
            if (r.get("license") or {}).get("spdx_id", "").lower() in ALLOWED_LICENSES]
    print(f"去重后 {before}，license 过滤后 {len(pool)}")

    with cf.ThreadPoolExecutor(16) as ex:
        verdicts = list(ex.map(lambda r: (r, jest_declared(r["full_name"])), pool))
    jest_repos = [r for r, (ok, _) in verdicts if ok]
    from collections import Counter
    print("探测结果分布:", Counter(note for _, (_, note) in verdicts))
    print(f"Jest 声明仓库: {len(jest_repos)}")

    # 排除所有已判定过的仓库（原池 + 前几轮扩池，以 summary 最后一行为准）
    already = set()
    try:
        with open(SUMMARY, newline="") as f:
            already = {r["full_name"] for r in csv.DictReader(f)}
    except OSError:
        pass
    fresh = [r for r in jest_repos if r["full_name"] not in already]
    print(f"排除已判定 {len(jest_repos) - len(fresh)} 个，新增候选 {len(fresh)}")

    fresh.sort(key=lambda r: -r["stargazers_count"])
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["full_name", "html_url", "stargazers_count", "size_kb", "pushed_at",
                    "language", "created_at", "license", "forks_count", "default_branch",
                    "description"])
        for r in fresh:
            w.writerow([r["full_name"], r["html_url"], r["stargazers_count"], r["size"],
                        r["pushed_at"], r.get("language", ""), r.get("created_at", ""),
                        (r.get("license") or {}).get("spdx_id", ""), r.get("forks_count", ""),
                        r.get("default_branch", ""),
                        (r.get("description") or "").replace("\n", " ")[:200]])
    print(f"已写出 {OUT}")


if __name__ == "__main__":
    main()
