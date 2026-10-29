"""Parallel orchestrator for the exp2 matrix (4 bug versions x 10 functions)."""
import subprocess, sys, os
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
VERSIONS = ["v2", "v3", "v4", "v5"]
N = 10

# 1) ensure orig sessions 0..9
subprocess.run([sys.executable, os.path.join(HERE, "adversary.py"), "setup-orig"],
               check=True, cwd=ROOT)
import json
for i in range(6, 10):
    pass  # setup-orig creates 0..5 only; create 6..9 here
for i in range(6, 10):
    name = f"pit_orig_f{i}"
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    subprocess.run(["docker", "run", "-d", "--name", name, "databind-iter:base", "sleep", "infinity"],
                   check=True, capture_output=True)
print("orig sessions ready")

def run_item(item):
    v, i = item
    import json as _json
    base = os.path.join(HERE, "..", "artifacts", "exp2", v, f"f{i}")
    def _ok(t):
        p2 = os.path.join(base, f"fresh_{t}.json")
        if not os.path.exists(p2):
            return False
        try:
            return _json.load(open(p2)).get("verdict") != "suite_broken"
        except Exception:
            return False
    if all(_ok(t) for t in ("T0", "T1", "T2")):
        print(f"skip {v}_f{i} (complete)", flush=True)
        return item, 0
    # drop stale broken records so the driver regenerates those variants
    for t in ("T0", "T1", "T2"):
        p2 = os.path.join(base, f"fresh_{t}.json")
        if os.path.exists(p2):
            try:
                if _json.load(open(p2)).get("verdict") == "suite_broken":
                    os.remove(p2)
            except Exception:
                pass
    log = open(os.path.join(os.path.dirname(HERE), "artifacts", "exp2", f"{v}_f{i}.log"), "w")
    r = subprocess.run([sys.executable, os.path.join(HERE, "exp2_driver.py"), "all", v, str(i)],
                       stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
    return item, r.returncode

items = [(v, i) for v in VERSIONS for i in range(N)]
with ThreadPoolExecutor(max_workers=6) as ex:
    futs = [ex.submit(run_item, it) for it in items]
    done = 0
    for f in as_completed(futs):
        item, rc = f.result()
        done += 1
        print(f"[{done}/{len(items)}] {item[0]}_f{item[1]} exit={rc}", flush=True)
print("ALL ITEMS DONE")
