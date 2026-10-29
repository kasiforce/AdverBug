"""Adversary evaluation driver with a reusable suite library.

Efficiency model:
- Suite library per function: suites that ever ran during iteration, each with
  per-test results on the ORIGINAL code (mechanical docker run, no LLM).
- precheck(bug)   : run every library suite on the bug; any test that passed on
                    original and FAILED (assertion) on the bug => detected, no
                    LLM needed.
- differential(fresh_suite, bug): run fresh suite on bug AND on original;
                    detection = passed-on-original && failed-on-bug. The fresh
                    suite is registered into the library afterwards.

CLI:
  python3 scripts/adversary.py setup-orig                 # start pit_orig_f{0..5}
  python3 scripts/adversary.py register <i> <tag> <file>  # run suite on original, add to library
  python3 scripts/adversary.py precheck <session> <i>     # run library on bug session
  python3 scripts/adversary.py fresh <session> <i> <tag> <file>  # differential verdict + register
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIB = os.path.join(ROOT, "artifacts", "suitelib")
RUNNER = os.path.join(HERE, "runner.py")


def _sh(args):
    r = subprocess.run([sys.executable, RUNNER] + args,
                       capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        raise RuntimeError(f"runner {args} failed: {r.stderr[-500:]}")
    line = [l for l in r.stdout.strip().splitlines() if l.startswith("{")][-1]
    return json.loads(line)


def load_index(i):
    p = os.path.join(LIB, f"f{i}", "index.json")
    if os.path.exists(p):
        return json.load(open(p))
    return {"suites": {}}


def save_index(i, idx):
    os.makedirs(os.path.join(LIB, f"f{i}"), exist_ok=True)
    with open(os.path.join(LIB, f"f{i}", "index.json"), "w") as f:
        json.dump(idx, f, indent=1)


def run_suite(session, i, suite_file):
    """write -> test-compile -> run. Returns dict with compile_ok/results/verdict."""
    _sh(["clean_test", session, str(i)])
    _sh(["write_test", session, str(i), suite_file])
    tc = _sh(["test_compile", session])
    if not tc.get("ok"):
        return {"compile_ok": False}
    rt = _sh(["run_tests", session, str(i)])
    return {"compile_ok": True, "results": rt.get("results", {}),
            "verdict": rt.get("verdict")}


def orig_session(i):
    return f"pit_orig_f{i}"


def setup_orig():
    for i in range(6):
        name = orig_session(i)
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        subprocess.run(["docker", "run", "-d", "--name", name,
                        "databind-iter:base", "sleep", "infinity"],
                       check=True, capture_output=True)
    print(json.dumps({"ok": True}))


def register(i, tag, suite_file):
    r = run_suite(orig_session(i), i, suite_file)
    idx = load_index(i)
    passed = sum(1 for v in r.get("results", {}).values() if v == "passed")
    idx["suites"][tag] = {"file": os.path.relpath(suite_file, ROOT),
                          "orig": r}
    save_index(i, idx)
    print(json.dumps({"tag": tag, "compile_ok": r.get("compile_ok", False),
                      "orig_passed": passed,
                      "orig_verdict": r.get("verdict")}))


def _diff(orig_results, bug_results):
    det, err = [], []
    for t, s in bug_results.items():
        if s == "failed" and orig_results.get(t) == "passed":
            det.append(t)
        elif s == "error" and orig_results.get(t) == "passed":
            err.append(t)
    return det, err


def precheck(session, i):
    idx = load_index(i)
    summary = {}
    any_detected = False
    for tag, info in idx["suites"].items():
        r = run_suite(session, i, os.path.join(ROOT, info["file"]))
        if not r.get("compile_ok"):
            summary[tag] = {"compile_ok": False}
            continue
        det, err = _diff(info["orig"].get("results", {}), r["results"])
        summary[tag] = {"detected": det, "errors": err,
                        "bug_verdict": r["verdict"]}
        if det:
            any_detected = True
    print(json.dumps({"detected": any_detected, "detail": summary}))


def fresh(session, i, tag, suite_file):
    rb = run_suite(session, i, suite_file)
    if not rb.get("compile_ok"):
        print(json.dumps({"compile_ok": False, "stage": "bug"}))
        return
    ro = run_suite(orig_session(i), i, suite_file)
    det, err = _diff(ro.get("results", {}), rb["results"])
    # register into library with its on-original results
    idx = load_index(i)
    idx["suites"][tag] = {"file": os.path.relpath(suite_file, ROOT), "orig": ro}
    save_index(i, idx)
    print(json.dumps({
        "compile_ok": True,
        "detected": det,
        "errors": err,
        "bug_verdict": rb["verdict"],
        "orig_verdict": ro.get("verdict"),
        "bug_nonpassed": {k: v for k, v in rb["results"].items() if v != "passed"},
    }))


def main():
    cmd = sys.argv[1]
    if cmd == "setup-orig":
        setup_orig()
    elif cmd == "register":
        register(int(sys.argv[2]), sys.argv[3], sys.argv[4])
    elif cmd == "precheck":
        precheck(sys.argv[2], int(sys.argv[3]))
    elif cmd == "fresh":
        fresh(sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5])


if __name__ == "__main__":
    main()
