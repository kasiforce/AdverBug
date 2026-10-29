"""Disposable mini-SWE-style replay for one saved Java bug.

The model can use Bash inside the disposable testbed container.  The host
restores the saved buggy production source before independently verifying the
test, so editing production code cannot make a candidate pass.
"""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path

from openai import OpenAI

from adver_dual import (compile_test_suite, evaluate_filter_model, read_text,
                        set_src_code, write_text)
from filter_test_gen import FilterTestGenerationAgent
from llm_config import LLMConfig
from mini_swe_test_agent import MiniSweTestAgent
from replay_filter_model import saved_bug
from usage_tracker import usage_tracker

TOOL = [{"type": "function", "function": {"name": "bash", "description": (
    "Run a Bash command in the disposable repository. You may inspect source, write only "
    "the requested test file, and run Maven commands to compile or run that test."),
    "parameters": {"type": "object", "properties": {"command": {"type": "string"}},
                   "required": ["command"]}}}]
RAW_CALL = re.compile(r"<function=bash>\s*<parameter=command>\s*(.*?)\s*</parameter>\s*</function>", re.S)


class BashFilterAgent(FilterTestGenerationAgent):
    def __init__(self, config, *, test_file):
        super().__init__(config, suite_retries=1, use_production_tools=False)
        self.test_file = test_file
        self.tool_trace = []
        self.client = OpenAI(api_key=config.API_KEY, base_url=config.API_ENDPOINT,
                             timeout=config.REQUEST_TIMEOUT, max_retries=0)

    def _run_agent(self, task: str) -> str:
        messages = [{"role": "system", "content": "You are a Java testing agent. "
                     "Use Bash to inspect the repository and iteratively create a specification-driven test. "
                     "You have at most 20 Bash tool calls total: plan them, and finish writing and "
                     "compiling the test before the budget is exhausted. Do not modify production "
                     "source files. When finished, write the complete test "
                     f"to exactly {self.test_file}."},
                    {"role": "user", "content": task}]
        for used in range(20):
            response = self.client.chat.completions.create(
                model=self.model_name, messages=messages, tools=TOOL, tool_choice="auto",
                temperature=0.2, max_tokens=16384)
            usage_tracker.record(self.model_name, response)
            message = response.choices[0].message
            calls = getattr(message, "tool_calls", None) or []
            raw = None if calls else RAW_CALL.search(message.content or "")
            if not calls and not raw:
                break
            if raw:
                calls = [type("Call", (), {"id": f"bash-{used}", "function": type("Fn", (), {
                    "name": "bash", "arguments": json.dumps({"command": raw.group(1).strip()})})})]
            messages.append({"role": "assistant", "content": message.content or "",
                             "tool_calls": [{"id": c.id, "type": "function", "function": {
                                 "name": c.function.name, "arguments": c.function.arguments}} for c in calls]})
            for call in calls:
                try:
                    command = json.loads(call.function.arguments).get("command", "")
                    result = subprocess.run(["bash", "-lc", command], cwd="/testbed", text=True,
                        capture_output=True, timeout=120,
                        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp"})
                    output = (result.stdout + result.stderr)[-12000:]
                    observation = f"$ {command}\n[returncode: {result.returncode}]\n{output}"
                    self.tool_trace.append({"command": command, "returncode": result.returncode,
                                            "output": output})
                except Exception as error:
                    observation = f"ERROR running command: {error}"
                    self.tool_trace.append({"command": getattr(call.function, "arguments", ""),
                                            "error": str(error)})
                if used == 19:
                    observation += "\nTool budget exhausted. Finish by writing the requested test file now."
                messages.append({"role": "tool", "tool_call_id": call.id, "content": observation})
        return read_text(self.test_file) if os.path.exists(self.test_file) else ""

    def generate_tests(self, entry, bug_code):
        self.current_entry = entry
        return self._run_agent(f"""Your job is to output a test class that invokes the code under test.
The supplied implementation may contain defects. Treat the specification as the primary source of truth for expected behavior; do not derive expected outputs solely from the implementation under test.

Design tests that distinguish a correct implementation from the supplied implementation: derive assertions from the specification so correct code passes and the supplied code fails. Do not use empty tests, tautologies, catch-and-ignore blocks, local replacement stubs, or expected values copied from the supplied implementation.

## Function:
```java
{bug_code}
```

## Specification:
{entry.get('specification', '')}

The test source path is {self.test_file}. Inspect APIs instead of guessing, compile it, and leave the final complete test at that path.""")

    def fix_compile(self, tests, error):
        write_text(self.test_file, tests)
        return self._run_agent(f"""Repair the test at {self.test_file}. Maven reported:\n{error}\n
Inspect source and compile until corrected. Preserve meaningful assertions and do not modify production source.""")

    def repair_tests(self, tests, error):
        return self.fix_compile(tests, error)


def main():
    parser = argparse.ArgumentParser()
    for key in ("data_path", "stats_path", "name", "model", "results_path"):
        parser.add_argument("--" + key.replace("_", "-"), required=True)
    parser.add_argument("--index", type=int, required=True)
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--endpoint", default="https://openrouter.ai/api/v1")
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--wall-timeout", type=int, default=1200)
    args = parser.parse_args()
    data = json.loads(Path(args.data_path).read_text())
    entry = data[args.index]
    bug = saved_bug(args.stats_path, args.name, args.attempt)
    uses_gpt = args.model.lower().startswith(("gpt-", "openai/gpt-"))
    key_name = "GPT_API_KEY" if uses_gpt else "QWEN_API_KEY"
    config = LLMConfig(os.environ[key_name], args.endpoint, args.model)
    source_before, test_before = read_text(entry["src_file"]), (read_text(entry["test_file"])
        if os.path.exists(entry["test_file"]) else None)
    usage_tracker.reset()
    try:
        if not set_src_code(entry["src_file"], bug, entry["code"]):
            raise RuntimeError("unable to apply saved bug")
        agent = MiniSweTestAgent(config, step_limit=args.steps,
                                 wall_time_limit=args.wall_timeout)
        undetected, tests, info = evaluate_filter_model(agent, entry, bug, entry["src_file"],
            entry["code"], entry["test_file"], suite_retries=1)
        result = {"undetected": undetected, "filter_result": info, "generated_tests": tests,
                  "tool_trace": agent.tool_trace,
                  "llm_usage": usage_tracker.summary()}
    finally:
        write_text(entry["src_file"], source_before)
        if test_before is None:
            if os.path.exists(entry["test_file"]): os.remove(entry["test_file"])
        else: write_text(entry["test_file"], test_before)
    Path(args.results_path).parent.mkdir(parents=True, exist_ok=True)
    Path(args.results_path).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "generated_tests"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
