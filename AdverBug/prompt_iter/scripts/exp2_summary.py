"""Aggregate exp2 matrix results into comparison tables.

Outputs (JSON + markdown rows) per bug-version:
  - attempt-1 escape rate under each test variant (differential & protocol)
  - prefilter hit rate, compile failure rate
  - per-test-variant false-positive-prone suite rate (suites with tests failing on orig)
"""
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXP = os.path.join(ROOT, "artifacts", "exp2")
VERSIONS = ["v2", "v3", "v4", "v5"]
VARIANTS = ["T0", "T1", "T2"]
N = 10


def load(v, i, name):
    p = os.path.join(EXP, v, f"f{i}", name)
    if os.path.exists(p):
        if name.endswith(".json"):
            try:
                with open(p) as f:
                    return json.load(f)
            except Exception:
                return None
        with open(p) as f:
            return f.read()
    return None


def main():
    summary = {}
    for v in VERSIONS:
        rows = []
        for i in range(N):
            bug = load(v, i, "buggy_code.java")
            comp = load(v, i, "compile.json")
            pre = load(v, i, "precheck.json")
            item = {"idx": i, "bug": bool(bug),
                    "compile_ok": bool(comp and comp.get("ok")),
                    "prefilter_detected": bool(pre and pre.get("detected")),
                    "variants": {}}
            for t in VARIANTS:
                fr = load(v, i, f"fresh_{t}.json")
                if fr is None:
                    item["variants"][t] = {"status": "missing"}
                elif fr.get("verdict") == "suite_broken":
                    item["variants"][t] = {"status": "suite_broken", "stage": fr.get("stage")}
                else:
                    item["variants"][t] = {
                        "status": "ok",
                        "detected_diff": bool(fr.get("detected")),
                        "detected_protocol": bool(fr.get("protocol_detected")),
                        "fp_tests": len(fr.get("false_positive_tests", [])),
                        "orig_fp_rate": (sum(1 for x in fr.get("orig_results", {}).values() if x != "passed")
                                         / max(1, len(fr.get("orig_results", {})))),
                    }
            rows.append(item)
        summary[v] = rows

    with open(os.path.join(EXP, "summary.json"), "w") as f:
        json.dump(summary, f, indent=1)

    # markdown table
    print("| bug版本 | 预过滤命中 | 编译失败 | T0逃逸(差分/协议) | T1逃逸(差分/协议) | T2逃逸(差分/协议) | T1假阳套件率 | T2假阳套件率 |")
    print("|---|---|---|---|---|---|---|---|")
    for v in VERSIONS:
        rows = summary[v]
        n = len(rows)
        pre = sum(1 for r in rows if r["prefilter_detected"])
        cf = sum(1 for r in rows if r["bug"] and not r["compile_ok"])
        line = [v, f"{pre}/{n}", f"{cf}/{n}"]
        fps = {}
        for t in VARIANTS:
            ok = [r["variants"][t] for r in rows if r["variants"][t]["status"] == "ok"]
            esc_diff = sum(1 for x in ok if not x["detected_diff"])
            esc_proto = sum(1 for x in ok if not x["detected_protocol"])
            broken = sum(1 for r in rows if r["variants"][t]["status"] == "suite_broken")
            line.append(f"{esc_diff}/{len(ok)} (+{broken}坏)")
            fps[t] = (sum(1 for x in ok if x["fp_tests"] > 0) / len(ok)) if ok else None
        for t in VARIANTS:
            line.append(f"{fps[t]:.0%}" if fps[t] is not None else "-")
        # reorder: we appended T0,T1,T2 then fps; build properly below
        print("| " + " | ".join(line[:6]) + " | " + " | ".join(line[6:]) + " |")

    with open(os.path.join(EXP, "summary.md"), "w") as f:
        f.write("| 版本 | 函数 | 每变体结果 |\n|---|---|---|\n")
        for v in VERSIONS:
            for r in summary[v]:
                vs = ", ".join(f"{t}:{x['status'] if x['status']!='ok' else ('DET' if x['detected_diff'] else 'esc')}"
                               for t, x in r["variants"].items())
                f.write(f"| {v} | f{r['idx']} | pre={'Y' if r['prefilter_detected'] else 'N'} comp={'Y' if r['compile_ok'] else 'N'} {vs} |\n")
    print("\nsaved summary.json / summary.md")


if __name__ == "__main__":
    main()
