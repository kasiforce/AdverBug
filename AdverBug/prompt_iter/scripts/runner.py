"""Docker-based compile & test runner mirroring adver_dual.py's mvn semantics
on the databind-iter:base image (jackson-databind @ pinned commit + junit4 deps).

One throwaway container per (entry, attempt). Steps:
  start -> patch(src, buggy) -> compile [-> fix loop outside] ->
  per model: write_test -> test-compile [-> fix loop outside] -> run -> parse surefire
  -> stop

Granular CLI (prints JSON to stdout):
  start <tag>                       -> {"session": "..."}
  patch <session> <entry_idx> <buggy_code_file>
  compile <session>
  write_test <session> <entry_idx> <tests_file>
  test_compile <session>
  run_tests <session> <entry_idx>   -> parse surefire, classify passed/failed/error
  clean_test <session> <entry_idx>  # remove test file + stale classes between models
  stop <session>
"""
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

IMAGE = "databind-iter:base"
DATA_PATH = "/data/home/cjy/SoftwareTestingBenchmark/databind_specification.json"
MVN_SKIP = "-Drat.skip=true -Dformatter.skip=true -DforkCount=0"


def _exec(session, cmd, timeout=1800):
    r = subprocess.run(["docker", "exec", session, "bash", "-c", cmd],
                       capture_output=True, text=True, timeout=timeout)
    return r


def _copy_text(session, path, text):
    r = subprocess.run(["docker", "exec", "-i", session, "bash", "-c", f"cat > '{path}'"],
                       input=text, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"copy to {path} failed: {r.stderr}")


def load_entries():
    with open(DATA_PATH) as f:
        return json.load(f)


def cmd_start(tag):
    name = f"pit_{tag}"
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    subprocess.run(["docker", "run", "-d", "--name", name, IMAGE, "sleep", "infinity"],
                   check=True, capture_output=True)
    print(json.dumps({"session": name}))
    return name


def _entry(idx):
    return load_entries()[int(idx)]


def cmd_patch(session, idx, buggy_file):
    e = _entry(idx)
    with open(buggy_file) as f:
        buggy = f.read().strip()
    src = _exec(session, f"cat '/testbed/{e['src_file']}'").stdout
    if e["code"] not in src:
        print(json.dumps({"ok": False, "reason": "original code not found in src file"}))
        return
    _copy_text(session, f"/testbed/{e['src_file']}", src.replace(e["code"], buggy))
    print(json.dumps({"ok": True}))


def cmd_compile(session):
    r = _exec(session, f"cd /testbed && mvn compile {MVN_SKIP} 2>&1")
    print(json.dumps({"ok": r.returncode == 0,
                      "tail": r.stdout[-6000:] if r.returncode != 0 else ""}))


def cmd_write_test(session, idx, tests_file):
    e = _entry(idx)
    with open(tests_file) as f:
        tests = f.read().strip()
    _exec(session, "mkdir -p '/testbed/%s'" % os.path.dirname(e["test_file"]))
    _copy_text(session, f"/testbed/{e['test_file']}", tests)
    print(json.dumps({"ok": True}))


def cmd_test_compile(session):
    r = _exec(session, f"cd /testbed && mvn test-compile {MVN_SKIP} 2>&1")
    print(json.dumps({"ok": r.returncode == 0,
                      "tail": r.stdout[-6000:] if r.returncode != 0 else ""}))


def _purge_test_class(session, test_file):
    cls = os.path.splitext(os.path.basename(test_file))[0]
    _exec(session,
          "bash -O globstar -c 'rm -f /testbed/**/target/test-classes/%s.class "
          "/testbed/**/target/test-classes/%s\\$*.class' 2>/dev/null; true" % (cls, cls))


def cmd_clean_test(session, idx):
    e = _entry(idx)
    _exec(session, f"rm -f '/testbed/{e['test_file']}'")
    _purge_test_class(session, e["test_file"])
    _exec(session, "bash -c \"find /testbed -type d -name surefire-reports -exec rm -rf {} + 2>/dev/null\"; true")
    print(json.dumps({"ok": True}))


def cmd_run_tests(session, idx):
    e = _entry(idx)
    cls = os.path.splitext(os.path.basename(e["test_file"]))[0]
    _exec(session, "bash -c \"find /testbed -type d -name surefire-reports -exec rm -rf {} + 2>/dev/null\"; true")
    r = _exec(session, f"cd /testbed && mvn test {MVN_SKIP} -Dtest={cls} 2>&1", timeout=1800)
    # parse surefire xmls inside the container
    pj = _exec(session, '''python3 - <<'EOF'
import glob, json, xml.etree.ElementTree as ET
res = {}
for p in glob.glob('/testbed/**/surefire-reports/TEST-*.xml', recursive=True):
    try:
        root = ET.parse(p).getroot()
    except Exception:
        continue
    for tc in root.iter('testcase'):
        key = tc.get('classname','') + '.' + tc.get('name','')
        if tc.find('error') is not None:
            res[key] = 'error'
        elif tc.find('failure') is not None:
            res[key] = 'failed'
        elif tc.find('skipped') is not None:
            res[key] = 'skipped'
        else:
            res[key] = 'passed'
print(json.dumps(res))
EOF''')
    try:
        results = json.loads(pj.stdout.strip().splitlines()[-1])
    except Exception:
        results = {}
    executed = {k: v for k, v in results.items() if v != "skipped"}
    failures = sorted(k for k, v in executed.items() if v == "failed")
    errors = sorted(k for k, v in executed.items() if v == "error")
    if executed and not failures and not errors and r.returncode == 0:
        verdict = "escaped"          # passed_on_buggy
    elif failures:
        verdict = "detected"         # assertion failure => filter model caught it
    elif not executed:
        verdict = "no_tests_executed"
    else:
        verdict = "errors_only"      # suite problem -> repair loop
    print(json.dumps({"verdict": verdict, "rc": r.returncode,
                      "results": results,
                      "tail": r.stdout[-6000:]}))


def cmd_stop(session):
    subprocess.run(["docker", "rm", "-f", session], capture_output=True)
    print(json.dumps({"ok": True}))


def main():
    cmds = {
        "start": lambda a: cmd_start(a[0]),
        "patch": lambda a: cmd_patch(a[0], a[1], a[2]),
        "compile": lambda a: cmd_compile(a[0]),
        "write_test": lambda a: cmd_write_test(a[0], a[1], a[2]),
        "test_compile": lambda a: cmd_test_compile(a[0]),
        "run_tests": lambda a: cmd_run_tests(a[0], a[1]),
        "clean_test": lambda a: cmd_clean_test(a[0], a[1]),
        "stop": lambda a: cmd_stop(a[0]),
    }
    cmds[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
