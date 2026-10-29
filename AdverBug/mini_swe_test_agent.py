"""Lightweight continuous Bash agent for Java test generation.

This keeps the useful mini-SWE interaction pattern without importing its
framework: the model repeatedly calls one Bash tool in the current disposable
project container, writes the requested test, and submits when finished.
"""
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

from openai import OpenAI

from usage_tracker import usage_tracker


BASH_TOOL = [{"type": "function", "function": {
    "name": "bash",
    "description": "Execute a Bash command in the current project container.",
    "parameters": {"type": "object", "properties": {
        "command": {"type": "string", "description": "The Bash command to execute."}
    }, "required": ["command"]},
}}]
RAW_BASH_CALL = re.compile(
    r"<function=bash>\s*<parameter=command>\s*(.*?)\s*</parameter>\s*</function>", re.S)
SUBMIT_COMMAND = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
MAX_CONSECUTIVE_FORMAT_ERRORS = 3


class MiniSweTestAgent:
    """OpenAI-compatible continuous Bash test agent."""

    # This agent inspects, writes, compiles, and repairs inside one continuous
    # Bash conversation.  The outer evaluator must only verify its submission;
    # it must not start another repair conversation for the same suite.
    self_managed_repairs = True

    def __init__(self, config, *, step_limit=100, wall_time_limit=1200):
        self.config = config
        self.model_name = config.MODEL_NAME
        self.step_limit = step_limit
        self.wall_time_limit = wall_time_limit
        self.client = OpenAI(api_key=config.API_KEY, base_url=config.API_ENDPOINT,
                             timeout=config.REQUEST_TIMEOUT, max_retries=0)
        self.current_entry = None
        self.current_bug = ""
        self.tool_trace = []

    @staticmethod
    def _production_snapshot():
        return {path: path.read_text(encoding="utf-8")
                for path in Path("/testbed").glob("**/src/main/java/**/*.java")}

    @staticmethod
    def _restore_production(snapshot):
        for path in Path("/testbed").glob("**/src/main/java/**/*.java"):
            if path not in snapshot:
                path.unlink()
        for path, content in snapshot.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    @staticmethod
    def _hide_existing_tests(test_file):
        target = Path(test_file)
        for test_root in Path("/testbed").glob("**/src/test"):
            if test_root.is_dir():
                subprocess.run(["find", str(test_root), "-type", "f", "-delete"], check=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.unlink(missing_ok=True)
        git_dir = Path("/testbed/.git")
        if git_dir.is_dir():
            subprocess.run(["rm", "-rf", str(git_dir)], check=False)

    def _run_bash(self, command):
        process = None
        try:
            process = subprocess.Popen(
                ["bash", "-lc", command], cwd="/testbed", text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                env=os.environ | {"PAGER": "cat", "MANPAGER": "cat"},
                start_new_session=True)
            output, _ = process.communicate(timeout=240)
            returncode = process.returncode
            output = output or ""
            if len(output) > 12000:
                output = (
                    "<warning>The command produced too much output. Use a narrower path, "
                    "grep pattern, or sed range on the next call.</warning>\n"
                    "<output_head>\n" + output[:6000]
                    + "\n</output_head>\n... [output truncated] ...\n<output_tail>\n"
                    + output[-6000:] + "\n</output_tail>"
                )
            self.tool_trace.append({"command": command, "returncode": returncode,
                                    "output": output[-2000:]})
            return returncode, output
        except subprocess.TimeoutExpired as error:
            if process is not None:
                os.killpg(process.pid, signal.SIGKILL)
                output, _ = process.communicate()
            else:
                output = error.stdout or ""
            self.tool_trace.append({"command": command, "returncode": -1,
                                    "output": "command timed out"})
            return -1, f"{output}\nCommand timed out after 240 seconds."

    def _run_agent(self, task):
        test_file = self.current_entry["test_file"]
        messages = [{"role": "system", "content": (
            "You are a Java testing agent working interactively in /testbed through one Bash tool. "
            "Every response must call Bash; you have at most "
            f"{self.step_limit} interaction steps. Each call runs in a fresh subshell rooted at "
            "/testbed, so directory and environment changes do not persist. Use non-interactive "
            "commands. Keep searches inside /testbed and scope grep, find, and sed to relevant "
            "source or build paths; never search '..' or the filesystem root. Do not use git, the "
            "network, or install dependencies.\n\n"
            "Read only the minimum relevant production source and build configuration. Do not read "
            "existing test sources. Do not modify production source, build configuration, generated "
            f"artifacts, or unrelated files; create or modify only {test_file}.\n\n"
            "Workflow: inspect the target and the project's test command, design focused behavioral "
            "cases from the specification, write the requested test, compile it, and run that exact "
            "test. Confirm that at least one test case executed; test-compile or a successful build "
            "with zero selected tests is not enough. Repair compilation, discovery, fixture, import, "
            "and runtime/setup errors without weakening behavioral assertions. An assertion failure "
            "derived from the specification is a successful detection of the supplied implementation: "
            "keep it and submit rather than changing the expected behavior. Inspect the final file "
            "before submitting.\n\n"
            f"Submit only after that workflow by executing `{SUBMIT_COMMAND}` as a standalone Bash "
            "call. Do not combine the submission command with compilation, testing, or another command.")},
            {"role": "user", "content": task}]
        started = time.monotonic()
        snapshot = self._production_snapshot()
        consecutive_format_errors = 0
        try:
            for step in range(self.step_limit):
                if time.monotonic() - started >= self.wall_time_limit:
                    self.tool_trace.append({"exit_status": "wall_time_limit", "api_calls": step})
                    break
                response = self.client.chat.completions.create(
                    model=self.model_name, messages=messages, tools=BASH_TOOL,
                    tool_choice="auto", temperature=0.2, max_tokens=16384)
                usage_tracker.record(self.model_name, response)
                message = response.choices[0].message
                model_calls = list(message.tool_calls or [])
                calls = [(call.id, json.loads(call.function.arguments).get("command", ""))
                         for call in model_calls if call.function.name == "bash"]
                if not calls:
                    raw = RAW_BASH_CALL.search(message.content or "")
                    if raw:
                        calls = [(f"raw-{step}", raw.group(1).strip())]
                    else:
                        consecutive_format_errors += 1
                        messages.append({"role": "assistant", "content": message.content or ""})
                        messages.append({"role": "user", "content":
                            "Your previous response did not call Bash. Respond concisely with exactly "
                            "one bash tool call. Continue inspecting, writing, compiling, or running "
                            "the requested test; submit only after the required test has executed."})
                        if consecutive_format_errors >= MAX_CONSECUTIVE_FORMAT_ERRORS:
                            self.tool_trace.append({"exit_status": "format_error_limit",
                                                    "api_calls": step + 1})
                            break
                        continue
                consecutive_format_errors = 0
                messages.append({"role": "assistant", "content": message.content or "",
                    "tool_calls": [{"id": call_id, "type": "function", "function": {
                        "name": "bash", "arguments": json.dumps({"command": command})}}
                        for call_id, command in calls]})
                submitted = False
                for call_id, command in calls:
                    returncode, output = self._run_bash(command)
                    submitted = (len(calls) == 1 and returncode == 0
                                 and command.strip() == SUBMIT_COMMAND)
                    remaining_steps = self.step_limit - step - 1
                    if remaining_steps <= 5:
                        output += (f"\n<interaction_steps_remaining>{remaining_steps}"
                                   "</interaction_steps_remaining>\n"
                                   "Finish the required test now. Do not spend the remaining "
                                   "steps on additional broad exploration.")
                    messages.append({"role": "tool", "tool_call_id": call_id,
                                     "content": f"<returncode>{returncode}</returncode>\n<output>{output}</output>"})
                if submitted:
                    self.tool_trace.append({"exit_status": "submitted", "api_calls": step + 1})
                    break
        finally:
            self._restore_production(snapshot)
        path = Path(test_file)
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def generate_tests(self, entry, bug_code):
        self.current_entry, self.current_bug = entry, bug_code
        self._hide_existing_tests(entry["test_file"])
        raw_framework = str(entry.get("test_framework") or "junit5").lower().replace(" ", "")
        framework = "JUnit 4" if raw_framework in {"junit4", "4"} else "JUnit 5"
        java_version = str(entry.get("java_version") or "17")
        return self._run_agent(f"""Your job is to create a test class that invokes the code under test.
The supplied implementation may contain defects. Treat the specification as the primary source of truth for expected behavior. Actively inspect related production code to understand the public API and fill in details that the specification leaves implicit: helper methods, related types, documentation, and independent call sites are useful semantic evidence. Reconcile that evidence with the specification instead of testing only its literal wording. Do not copy constants, branches, arguments, or results from the supplied implementation and treat them as expected behavior.

Before writing or editing the test, reason step by step internally: combine the specification with independently corroborated production-code evidence, identify the observable intended behavior, predict how the supplied implementation could differ from it, and choose an input and assertion that expose that difference. Do not write this reasoning into the test file or final response.

Design tests that distinguish a correct implementation from the supplied implementation: derive assertions from the specification so correct code passes and the supplied code fails. Do not use empty tests, tautologies, catch-and-ignore blocks, local replacement stubs, or expected values copied from the supplied implementation.

## Function:
```java
{bug_code}
```

## Specification:
{entry.get('specification', '')}

Configured test framework: {framework}
Configured Java version: {java_version}
The test source path is {entry['test_file']}.

Inspect APIs instead of guessing. Use {framework}, not another JUnit version. Compile the test and run that exact test before submitting, and verify that at least one case executes. Fix compilation, discovery, and runtime/setup errors. If a specification-based assertion fails on the supplied implementation, preserve it because it has detected the defect. Leave the final complete test at the required path.""")
