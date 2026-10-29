"""Render prompts EXACTLY as the real pipeline scripts do, by monkeypatching the
OpenAI client so that message payloads are captured instead of sent to an LLM.

Usage:
  python prompts_bridge.py dump-bug-init <out.json>
  python prompts_bridge.py render-test <entry_idx> <buggy_code_file> <out.json>
  python prompts_bridge.py render-enhance <entry_idx> <buggy_file> <testinfo_file> <out.json>
  python prompts_bridge.py render-fix-bug <buggy_file> <error_file> <out.json>
  python prompts_bridge.py render-fix-compile <tests_file> <error_file> <out.json>
  python prompts_bridge.py render-repair <tests_file> <failure_file> <out.json>
  python prompts_bridge.py render-validate <code_file> <buggy_file> <tests_file> <out.json>
"""
import json
import sys

ADVER = "/data/home/cjy/SoftwareTestingBenchmark/AdverBug"
sys.path.insert(0, ADVER)

import bug_generation_agent as bga  # noqa: E402
import test_gen as tg  # noqa: E402
import filter_test_gen as ftg  # noqa: E402
import valid_agent as va  # noqa: E402
from llm_config import LLMConfig  # noqa: E402

DATA_PATH = "/data/home/cjy/SoftwareTestingBenchmark/databind_specification.json"


class _FakeMsg:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMsg(content)


class _FakeResp:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


captured = []


class _FakeCompletions:
    def create(self, **kw):
        captured.append(kw)
        return _FakeResp('{"bug_summary":"ok","buggy_code":"ok"}')


class _FakeChat:
    completions = _FakeCompletions()


class FakeClient:
    chat = _FakeChat()


def _cfg():
    return LLMConfig(api_key="x", api_endpoint="http://localhost", model_name="dummy")


def _capture(fn):
    captured.clear()
    fn()
    m = captured[0]["messages"]
    return {"system": m[0]["content"], "user": m[1]["content"]}


def load_entries():
    with open(DATA_PATH) as f:
        return json.load(f)


def render_init_bug(code, specification=None):
    a = bga.BugGenerationAgent(llm_config=_cfg())
    a.client = FakeClient()
    return _capture(lambda: a.init_bug_prompt(code, specification))


def render_enhance_bug(code, buggy, test_info):
    a = bga.BugGenerationAgent(llm_config=_cfg())
    a.client = FakeClient()
    return _capture(lambda: a.enhance_bug_prompt(code, buggy, test_info))


def render_fix_bug(bug_code, error):
    a = bga.BugGenerationAgent(llm_config=_cfg())
    a.client = FakeClient()
    return _capture(lambda: a.fix_bug_prompt(bug_code, error))


def render_init_test(entry, buggy_code):
    a = tg.TestGenerationAgent(llm_config=_cfg())
    a.client = FakeClient()
    return _capture(lambda: a.init_test_prompt(buggy_code, entry))


def render_fix_compile(tests, error):
    ag = ftg.FilterTestGenerationAgent(_cfg(), 2)
    ag.client = FakeClient()
    return _capture(lambda: ag.fix_compile(tests, error))


def render_repair(tests, failure_output):
    ag = ftg.FilterTestGenerationAgent(_cfg(), 2)
    ag.client = FakeClient()
    return _capture(lambda: ag.repair_tests(tests, failure_output))


def render_validate(code, buggy_code, tests):
    ag = va.ValidAgent(llm_config=_cfg())
    ag.client = FakeClient()
    return _capture(lambda: ag.validate(code, buggy_code, tests))


def _read(p):
    with open(p) as f:
        return f.read()


def main():
    cmd = sys.argv[1]
    if cmd == "dump-bug-init":
        out = {}
        for i, e in enumerate(load_entries()):
            out[str(i)] = {"name": e["name"], **render_init_bug(e["code"], e.get("specification"))}
        with open(sys.argv[2], "w") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print("dumped", len(out))
    elif cmd == "render-test":
        entry = load_entries()[int(sys.argv[2])]
        buggy = _read(sys.argv[3])
        res = render_init_test(entry, buggy)
        with open(sys.argv[4], "w") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print("rendered test prompt ->", sys.argv[4])
    elif cmd == "render-enhance":
        entry = load_entries()[int(sys.argv[2])]
        buggy = _read(sys.argv[3])
        test_info = _read(sys.argv[4])
        res = render_enhance_bug(entry["code"], buggy, test_info)
        with open(sys.argv[5], "w") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print("rendered enhance prompt ->", sys.argv[5])
    elif cmd == "render-fix-bug":
        res = render_fix_bug(_read(sys.argv[2]), _read(sys.argv[3]))
        with open(sys.argv[4], "w") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print("ok")
    elif cmd == "render-fix-compile":
        res = render_fix_compile(_read(sys.argv[2]), _read(sys.argv[3]))
        with open(sys.argv[4], "w") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print("ok")
    elif cmd == "render-repair":
        res = render_repair(_read(sys.argv[2]), _read(sys.argv[3]))
        with open(sys.argv[4], "w") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print("ok")
    elif cmd == "render-validate":
        res = render_validate(_read(sys.argv[2]), _read(sys.argv[3]), _read(sys.argv[4]))
        with open(sys.argv[5], "w") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print("ok")
    else:
        raise SystemExit(f"unknown cmd {cmd}")


if __name__ == "__main__":
    main()
