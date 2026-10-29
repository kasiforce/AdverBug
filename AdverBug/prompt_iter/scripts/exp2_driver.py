"""exp2 driver: bug-prompt versions x test-prompt variants matrix on N functions.

Pipeline per (bug_version, function idx):
  1. buggen   : API bug generation (temperature 0.7, retry once on no-op/parse fail)
  2. compile  : mvn compile in throwaway container; on failure up to 2 API fix
                rounds using bug_generation_agent.fix_bug_prompt template
  3. precheck : library differential (orig-passing test failed on bug => detected)
  4. tests    : for each variant T0/T1/T2 (survivors only): API test generation,
                up to 2 fix-compile rounds + 1 regen, then differential fresh run
                (suite fails on orig too => recorded as false-positive-prone)

State layout: artifacts/exp2/{version}/f{idx}/...
  bug_raw.txt buggy_code.java compile.json fix1.java... precheck.json
  tests_{variant}.java fresh_{variant}.json

CLI:
  python3 exp2_driver.py buggen <version> <idx>
  python3 exp2_driver.py compile <version> <idx>
  python3 exp2_driver.py precheck <version> <idx>
  python3 exp2_driver.py tests <version> <idx> <variant>
  python3 exp2_driver.py all <version> <idx>      # stages 1-4 sequential
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, ".."))

DATA = os.environ.get("PROMPT_ITER_DATA",
                      os.path.join(ROOT, "databind_specification_10.json"))
API_KEY = os.environ.get("LLM_API_KEY", "")
ENDPOINT = os.environ.get("LLM_API_ENDPOINT", "https://api.agicto.cn/v1")
BUG_MODEL = os.environ.get("EXP2_BUG_MODEL", "gpt-5-nano")
TEST_MODEL = os.environ.get("EXP2_TEST_MODEL", "gpt-5-nano")

from prompt_versions import VERSIONS, _spec_text  # noqa: E402
from test_prompt_versions import render_variant, VARIANTS  # noqa: E402
from openai import OpenAI  # noqa: E402

if not API_KEY:
    raise RuntimeError("LLM_API_KEY must be set")

_client = OpenAI(api_key=API_KEY, base_url=ENDPOINT, timeout=900, max_retries=2)

import threading
import errno

_LOCKDIR = "/tmp/exp2_docker_gate"
_GATE_SIZE = 4

class _GlobalDockerGate:
    """Cross-process semaphore (mkdir-based): keeps total concurrent mvn runs <=2
    across all orchestrator processes (ErrorProne forks fail spuriously under load)."""
    def __enter__(self):
        os.makedirs(_LOCKDIR, exist_ok=True)
        while True:
            for n in range(_GATE_SIZE):
                slot = os.path.join(_LOCKDIR, f"slot{n}")
                try:
                    os.mkdir(slot)
                    self.slot = slot
                    return self
                except FileExistsError:
                    continue
            time.sleep(3)

    def __exit__(self, *a):
        try:
            os.rmdir(self.slot)
        except OSError:
            pass

_DOCKER_SEM = _GlobalDockerGate()


def _state(version, idx):
    d = os.path.join(ROOT, "artifacts", "exp2", version, f"f{idx}")
    os.makedirs(d, exist_ok=True)
    return d


def _entries():
    with open(DATA) as f:
        return json.load(f)


def _chat(system, user, temperature, max_tokens=16384, model=None):
    resp = _client.chat.completions.create(
        model=model or BUG_MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        temperature=temperature, max_tokens=max_tokens)
    return (resp.choices[0].message.content or "").strip()


def _fixsuite(tests_text):
    """Deterministic import/API fixes (project ruleset) before API repair."""
    import tempfile
    with tempfile.NamedTemporaryFile('w', suffix='.java', delete=False) as f:
        f.write(tests_text)
        path = f.name
    subprocess.run([sys.executable, os.path.join(HERE, 'fix_suite.py'),
                    '--ruleset', 'jackson', path], capture_output=True)
    out = open(path).read()
    os.unlink(path)
    return out


def _parse_bug_json(raw):
    b = raw.split("```json")[-1].split("```")[0].strip()
    if not b.startswith("{"):
        text = b.split("{")[0]
        b = b.split(text)[-1].strip()
    try:
        return json.loads(b)
    except Exception:
        st, en = raw.find("{"), raw.rfind("}")
        return json.loads(raw[st:en + 1])


# ---------------- bug generation ----------------

def stage_buggen(version, idx):
    d = _state(version, idx)
    entries = _entries()
    e = entries[idx]
    spec = e.get("specification", "")
    init_fn, enh_fn = VERSIONS[version]
    for attempt in range(2):
        system, user = init_fn(e["code"], spec)
        raw = _chat(system, user, 0.7)
        open(os.path.join(d, "bug_raw.txt"), "w").write(raw)
        try:
            obj = _parse_bug_json(raw)
        except Exception:
            time.sleep(2)
            continue
        code = (obj.get("buggy_code") or "").strip()
        if not code or code == e["code"]:
            time.sleep(2)
            continue
        open(os.path.join(d, "buggy_code.java"), "w").write(code)
        json.dump(obj, open(os.path.join(d, "bug_parsed.json"), "w"),
                  ensure_ascii=False, indent=1)
        print(json.dumps({"ok": True, "len": len(code)}))
        return
    print(json.dumps({"ok": False, "stage": "buggen"}))


# ---------------- compile ----------------

def _runner(*args):
    r = subprocess.run([sys.executable, os.path.join(HERE, "runner.py")] + list(args),
                       capture_output=True, text=True, cwd=ROOT)
    lines = [l for l in r.stdout.strip().splitlines() if l.startswith("{")]
    return json.loads(lines[-1]) if lines else {"ok": False}


def _session(version, idx, tag):
    name = f"pit_e2_{version}_f{idx}_{tag}"
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    subprocess.run(["docker", "run", "-d", "--name", name, "databind-iter:base",
                    "sleep", "infinity"], check=True, capture_output=True)
    return name


def _patch(session, idx, buggy_file):
    e = _entries()[idx]
    buggy = open(buggy_file).read().strip()
    src = _runner("start", "noop")  # noqa placeholder to keep import shape
    r = subprocess.run(["docker", "exec", session, "bash", "-c",
                        f"cat '/testbed/{e['src_file']}'"], capture_output=True, text=True)
    if e["code"] not in r.stdout:
        return False
    p = subprocess.run(["docker", "exec", "-i", session, "bash", "-c",
                        f"cat > '/testbed/{e['src_file']}'"],
                       input=r.stdout.replace(e["code"], buggy),
                       capture_output=True, text=True)
    return p.returncode == 0


_FIX_BUG_TMPL = """The code below fails to compile with the following error:
Code:
```java
{bug_code}
```

Error:
```
{error}
```

Please provide a corrected version of the code that compiles.

Only resolve the compilation error. Keep the existing logic, every comment, string literal, log message, and identifier exactly as in the code above - do not "fix" any behavior, and do not add, rewrite, or delete any comment.
```java
<corrected code>
```
"""

_FIX_COMPILE_TMPL = """The test code below fails to compile with the following error:
Tests:
```java
{tests}
```

Error:
```
{error}
```

Please provide a corrected version of the test code that compiles.
```java
<corrected test code>
```
"""

_REPAIR_TMPL = """The test code below has the following problems:
Tests:
```java
{tests}
```

Error:
```
{error}
```

Please provide a corrected version of the test code that compiles and passes on the correct implementation.
```java
<corrected test code>
```
"""


def stage_compile(version, idx):
    with _DOCKER_SEM:
        return _stage_compile(version, idx)


def _stage_compile(version, idx):
    d = _state(version, idx)
    e = _entries()[idx]
    session = _session(version, idx, "c")
    try:
        if not _patch(session, idx, os.path.join(d, "buggy_code.java")):
            json.dump({"ok": False, "stage": "patch"}, open(os.path.join(d, "compile.json"), "w"))
            print(json.dumps({"ok": False, "stage": "patch"}))
            return
        r = _runner("compile", session)
        fixes = 0
        buggy_code = open(os.path.join(d, "buggy_code.java")).read().strip()
        while not r["ok"] and fixes < 2:
            err = r.get("tail", "")
            fixed = _chat("You are a helpful assistant that fixes compilation errors in Java code while keeping its logic and comments unchanged.",
                          _FIX_BUG_TMPL.format(bug_code=buggy_code, error=err[-5000:]), 0.0)
            fixed = fixed.split("```java")[-1].split("```")[0].strip()
            if not fixed or fixed == buggy_code:
                break
            fixes += 1
            open(os.path.join(d, f"buggy_fix{fixes}.java"), "w").write(fixed)
            _patch(session, idx, os.path.join(d, f"buggy_fix{fixes}.java"))
            r = _runner("compile", session)
            buggy_code = fixed
        json.dump({"ok": r["ok"], "fixes": fixes, "tail": r.get("tail", "")[-3000:] if not r["ok"] else ""},
                  open(os.path.join(d, "compile.json"), "w"))
        print(json.dumps({"ok": r["ok"], "fixes": fixes}))
    finally:
        subprocess.run(["docker", "rm", "-f", session], capture_output=True)


# ---------------- precheck ----------------

def stage_precheck(version, idx):
    with _DOCKER_SEM:
        return _stage_precheck(version, idx)


def _stage_precheck(version, idx):
    d = _state(version, idx)
    r = subprocess.run([sys.executable, os.path.join(HERE, "adversary.py"),
                        "precheck", f"pit_orig_f{idx}", str(idx)],
                       capture_output=True, text=True, cwd=ROOT)
    out = r.stdout.strip().splitlines()
    res = json.loads(out[-1]) if out else {"detected": False, "detail": {}}
    json.dump(res, open(os.path.join(d, "precheck.json"), "w"), indent=1)
    print(json.dumps({"detected": res.get("detected", False)}))


# ---------------- tests ----------------

def stage_tests(version, idx, variant):
    # API part runs without the docker gate; docker part gated inside
    d = _state(version, idx)
    comp = json.load(open(os.path.join(d, "compile.json")))
    if not comp.get("ok"):
        print(json.dumps({"skip": "bug_compilation_failed"}))
        return
    pre = json.load(open(os.path.join(d, "precheck.json")))
    if pre.get("detected"):
        print(json.dumps({"skip": "precheck_detected"}))
        return
    e = _entries()[idx]
    buggy_file = os.path.join(d, "buggy_code.java")
    comp = json.load(open(os.path.join(d, "compile.json")))
    for f in range(comp.get("fixes", 0), 0, -1):
        cand = os.path.join(d, f"buggy_fix{f}.java")
        if os.path.exists(cand):
            buggy_file = cand
            break
    buggy = open(buggy_file).read().strip()

    system, user = render_variant(variant, e, buggy)
    tests = None
    for attempt in range(2):  # 1 regen
        raw = _chat(system, user, 0.0, model=TEST_MODEL)
        t = raw.split("```java")[-1].split("```")[0].strip()
        if t:
            tests = _fixsuite(t)
            break
    if not tests:
        json.dump({"verdict": "suite_broken", "stage": "gen"},
                  open(os.path.join(d, f"fresh_{variant}.json"), "w"))
        print(json.dumps({"verdict": "suite_broken", "stage": "gen"}))
        return

    with _DOCKER_SEM:
        return _stage_tests_docker(version, idx, variant, tests, buggy_file)


def _stage_tests_docker(version, idx, variant, tests, buggy_file):
    d = _state(version, idx)
    e = _entries()[idx]
    session = _session(version, idx, "t" + variant)
    try:
        final_bug = buggy_file
        # the bug side may have compile fixes; patch the final bug code
        src = json.load(open(os.path.join(d, "compile.json")))
        _patch(session, idx, buggy_file)
        cr = _runner("compile", session)
        ok_bug = cr["ok"]
        tag = os.path.splitext(os.path.basename(e["test_file"]))[0]
        cls = tag
        for fix_round in range(3):
            _runner("clean_test", session, str(idx))
            subprocess.run(["docker", "exec", "-i", session, "bash", "-c",
                            f"mkdir -p '/testbed/{os.path.dirname(e['test_file'])}' && cat > '/testbed/{e['test_file']}'"],
                           input=tests, capture_output=True, text=True)
            tc = _runner("test_compile", session)
            if not tc["ok"]:
                fixed = _chat("You are a helpful assistant that fixes failing test code.",
                              _FIX_COMPILE_TMPL.format(tests=tests, error=tc.get("tail", "")[-5000:]), 0.0)
                fixed = fixed.split("```java")[-1].split("```")[0].strip()
                if fixed and fixed != tests:
                    tests = _fixsuite(fixed)
                    continue
                json.dump({"verdict": "suite_broken", "stage": "test_compile"},
                          open(os.path.join(d, f"fresh_{variant}.json"), "w"))
                print(json.dumps({"verdict": "suite_broken", "stage": "test_compile"}))
                return
            rt = _runner("run_tests", session, str(idx))
            if "verdict" not in rt:
                rt = {"verdict": "errors_only", "results": {}, "tail": "runner failure (no output)"}
            if rt["verdict"] == "errors_only":
                rep = _chat("You are a helpful assistant that fixes failing test code.",
                            _REPAIR_TMPL.format(tests=tests, error=rt.get("tail", "")[-5000:]), 0.0)
                rep = rep.split("```java")[-1].split("```")[0].strip()
                if rep and rep != tests:
                    tests = _fixsuite(rep)
                    continue
                json.dump({"verdict": "suite_broken", "stage": "run_errors"},
                          open(os.path.join(d, f"fresh_{variant}.json"), "w"))
                print(json.dumps({"verdict": "suite_broken", "stage": "run_errors"}))
                return
            if rt["verdict"] == "no_tests_executed":
                rep = _chat("You are a helpful assistant that fixes failing test code.",
                            _REPAIR_TMPL.format(tests=tests, error="no tests were executed; the public test class name must match the file name in the prompt's test_path"), 0.0)
                rep = rep.split("```java")[-1].split("```")[0].strip()
                if rep and rep != tests:
                    tests = rep
                    continue
                json.dump({"verdict": "suite_broken", "stage": "no_tests_executed"},
                          open(os.path.join(d, f"fresh_{variant}.json"), "w"))
                print(json.dumps({"verdict": "suite_broken", "stage": "no_tests_executed"}))
                return
            # escaped or detected on bug: differential against orig
            orig_session = f"pit_orig_f{idx}"
            _runner("clean_test", orig_session, str(idx))
            subprocess.run(["docker", "exec", "-i", orig_session, "bash", "-c",
                            f"mkdir -p '/testbed/{os.path.dirname(e['test_file'])}' && cat > '/testbed/{e['test_file']}'"],
                           input=tests, capture_output=True, text=True)
            ro = _runner("run_tests", orig_session, str(idx))
            det = [t for t, s in rt["results"].items()
                   if s == "failed" and ro["results"].get(t) == "passed"]
            fp = [t for t, s in rt["results"].items()
                  if s in ("failed", "error") and ro["results"].get(t) not in ("passed",)]
            out = {"verdict": rt["verdict"], "detected": sorted(det),
                   "protocol_detected": any(v == "failed" for v in rt["results"].values()),
                   "false_positive_tests": sorted(fp)[:20],
                   "results": rt["results"], "orig_results": ro["results"]}
            json.dump(out, open(os.path.join(d, f"fresh_{variant}.json"), "w"), indent=1)
            open(os.path.join(d, f"tests_{variant}.java"), "w").write(tests)
            print(json.dumps({"variant": variant, "detected": bool(det),
                              "protocol_detected": out["protocol_detected"],
                              "bug_verdict": rt["verdict"], "orig_verdict": ro["verdict"]}))
            return
        json.dump({"verdict": "suite_broken", "stage": "fix_budget"},
                  open(os.path.join(d, f"fresh_{variant}.json"), "w"))
        print(json.dumps({"verdict": "suite_broken", "stage": "fix_budget"}))
    finally:
        subprocess.run(["docker", "rm", "-f", session], capture_output=True)


def main():
    cmd = sys.argv[1]
    if cmd == "all":
        version, idx = sys.argv[2], int(sys.argv[3])
        stage_buggen(version, idx)
        if not os.path.exists(os.path.join(_state(version, idx), "buggy_code.java")):
            print(json.dumps({"abort": "no bug"})); return
        stage_compile(version, idx)
        stage_precheck(version, idx)
        for variant in VARIANTS:
            stage_tests(version, idx, variant)
        print(json.dumps({"done": [version, idx]}))
        return
    if cmd == "tests":
        stage_tests(sys.argv[2], int(sys.argv[3]), sys.argv[4])
        return
    fn = {"buggen": stage_buggen, "compile": stage_compile, "precheck": stage_precheck}[cmd]
    fn(sys.argv[2], int(sys.argv[3]))


if __name__ == "__main__":
    main()
