"""Dual-filter adversarial bug generation for JavaScript/Jest projects.

The Java implementation in :mod:`adver_dual` edits a Maven project in place.
This version uses a disposable project copy, because JavaScript projects often
have a mixture of Jest, ESM and CommonJS configuration and are unsafe to
mutate in the source checkout.  For every candidate it:

1. asks the shared bug-generation model for a JavaScript mutation;
2. removes existing tests in test-like directories;
3. asks two independent models for Jest tests and repairs suites that do not
   pass on the original implementation;
4. runs each suite on the original and mutated implementation;
5. keeps a mutation only when the semantic judge considers it a real bug and
   both suites miss it.

Example::

    python AdverBug/adver_dual_js.py --data-path dataset/js/CyberChef.json \
      --results-path results/js_dual.json --stats-path results/js_stats.json

The project root can be supplied with ``--project-root``; otherwise the
``project_root`` field in each dataset entry is used.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bug_generation_agent import BugGenerationAgent  # noqa: E402
from llm_config import LLMConfig  # noqa: E402
from screen_js_repo import detect_build, find_jest_binary, setup_deps  # noqa: E402


def _load_test_cleaner():
    """Load the repository's canonical JavaScript test deletion routine."""
    try:
        from gen_test.gen_javascript_testfiles import delete_test_files_in_test_dirs
        return delete_test_files_in_test_dirs
    except (ImportError, AttributeError):
        return _fallback_delete_tests


def _fallback_delete_tests(project_root):
    """Conservative fallback matching the generator's test-directory policy."""
    test_names = {"test", "tests", "__test__", "__tests__", "testing"}
    ignored = {".git", "node_modules", "dist", "build", "coverage"}
    deleted = []
    root = Path(project_root)
    for directory, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ignored]
        if Path(directory).name.lower() not in test_names:
            continue
        for name in files:
            if Path(name).suffix.lower() in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}:
                path = Path(directory) / name
                try:
                    path.unlink()
                    deleted.append(str(path))
                except OSError:
                    pass
    return deleted


delete_test_files_in_test_dirs = _load_test_cleaner()


def _parse_json(text):
    decoder = json.JSONDecoder()
    text = (text or "").strip()
    candidates = [text]
    fenced = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.I | re.S)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    for candidate in candidates:
        try:
            value, _ = decoder.raw_decode(candidate)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    while start >= 0:
        try:
            value, _ = decoder.raw_decode(text[start:])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
        else:
            break
    return {}


def _extract_code(text):
    text = (text or "").strip()
    match = re.search(r"```(?:javascript|js|jsx|mjs|typescript|ts)?\s*\n?(.*?)```", text, re.I | re.S)
    if match:
        text = match.group(1).strip()
    return text.replace("```javascript", "").replace("```js", "").replace("```", "").strip()


def _tail(proc, limit=500):
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return output.strip()[-limit:]


class _JSLLMAgent:
    def __init__(self, config, *, temperature=0.0, max_tokens=16384, retries=2):
        from openai import OpenAI
        self.client = OpenAI(api_key=config.API_KEY, base_url=config.API_ENDPOINT, max_retries=0)
        self.model = config.MODEL_NAME
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.retries = retries

    def call(self, messages):
        last = None
        for attempt in range(self.retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model, messages=messages,
                    temperature=self.temperature, max_tokens=self.max_tokens,
                )
                return (response.choices[0].message.content or "").strip()
            except Exception as exc:  # network/API failures are retried
                last = exc
                if attempt < self.retries:
                    time.sleep(2 ** attempt)
        raise last


def function_context(entry, original_code, buggy_code=""):
    specification = entry.get("specification") or "Infer behavior from the original implementation and its surrounding module."
    if isinstance(specification, list):
        specification = "\n\n".join(map(str, specification))
    return f"""Function name: {entry.get('name', '')}
Source file: {entry.get('src_file', '')}
Test file: {entry.get('test_file', '')}
Class: {entry.get('class_name') or 'standalone function'}
Exported name: {entry.get('exported_name') or entry.get('class_exported_name') or ''}
Export kind: {entry.get('export_kind') or entry.get('class_export_kind') or 'unknown'}
Module imports recorded by the extractor: {entry.get('imports', [])}

Original function:
```javascript
{original_code}
```

Mutated function:
```javascript
{buggy_code}
```

Behavioral context:
{specification}
"""


class JavaScriptFilterAgent(_JSLLMAgent):
    """Generate and repair complete Jest test files."""
    def generate_tests(self, entry, original_code, buggy_code):
        prompt = f"""Generate a complete JavaScript unit-test file for Jest.
Return only source code, never Markdown or an explanation. The file must be
collectable by the project's existing Jest setup and must pass against the
original implementation. Follow the module system shown by the source file
(ESM import/export or CommonJS require/module.exports), use only dependencies
already available in the project, and import the target through its public
export whenever possible. Use describe/test(or it)/expect. Cover normal,
boundary, invalid-input, and relevant state/dependency behavior. Do not read
or reuse any pre-existing test file.

{function_context(entry, original_code, buggy_code)}"""
        return _extract_code(self.call([
            {"role": "system", "content": "You are a careful JavaScript test engineer working with Jest. Return only the requested test source."},
            {"role": "user", "content": prompt},
        ]))

    def repair_tests(self, entry, original_code, buggy_code, tests, feedback):
        prompt = f"""Repair this Jest test file so that it is valid for the
project's module system and passes against the original implementation.
Return only the complete test source. Preserve useful behavioral coverage;
fix imports, paths, setup, async handling, and assertions indicated by the
Jest output. Do not weaken tests merely by deleting assertions.

{function_context(entry, original_code, buggy_code)}

Current test file:
```javascript
{tests}
```

Jest feedback:
{feedback}
"""
        return _extract_code(self.call([
            {"role": "system", "content": "You repair Jest suites conservatively. Return only JavaScript test source."},
            {"role": "user", "content": prompt},
        ]))


class JavaScriptSemanticJudge(_JSLLMAgent):
    def __init__(self, config, **kwargs):
        super().__init__(config, temperature=0.3, max_tokens=4096, **kwargs)

    def validate(self, entry, original_code, buggy_code, tests):
        prompt = f"""Decide whether the candidate mutation is a real,
reachable JavaScript semantic bug. Ignore formatting, renaming, unreachable
code, equivalent rewrites, and syntax-only changes. Return JSON only:
{{\"is_valid_bug\": true/false, \"reason\": \"brief explanation\"}}.

{function_context(entry, original_code, buggy_code)}
Candidate Jest tests:
```javascript
{tests}
```"""
        value = _parse_json(self.call([
            {"role": "system", "content": "You are a conservative semantic bug judge for JavaScript."},
            {"role": "user", "content": prompt},
        ]))
        return value if isinstance(value.get("is_valid_bug"), bool) else {
            "is_valid_bug": False, "reason": "unparseable judge response"
        }


def js_specification(entry):
    """Add module metadata to the shared multi-language bug prompt."""
    return "\n".join([
        str(entry.get("specification") or "Infer behavior from code."),
        f"Module path: {entry.get('src_file', '')}",
        f"Recorded imports: {entry.get('imports', [])}",
        f"Export metadata: {entry.get('export_kind') or entry.get('class_export_kind') or 'unknown'} / {entry.get('exported_name') or entry.get('class_exported_name') or ''}",
    ])


def copy_project(source, destination):
    ignored_names = {".git", "dist", "build", "coverage", ".nyc_output", ".adverbug_jest_smoke", ".adverbug_jest_runtime"}
    def ignore(_directory, names):
        return [name for name in names if name in ignored_names]
    shutil.copytree(source, destination, ignore=ignore, symlinks=True)


def resolve_source_root(entry, explicit):
    if explicit and explicit.is_dir():
        return explicit.resolve()
    recorded = entry.get("project_root")
    if recorded and Path(recorded).is_dir():
        return Path(recorded).resolve()
    return None


def patch_function(source_file, entry, replacement):
    """Replace the extractor's line span, falling back to unique exact text."""
    original = source_file.read_text(encoding="utf-8", errors="ignore")
    lines = original.splitlines(keepends=True)
    start, end = entry.get("start_line"), entry.get("end_line")
    old = str(entry.get("code") or "")
    if isinstance(start, int) and isinstance(end, int) and 1 <= start <= end <= len(lines):
        selected = "".join(lines[start - 1:end])
        if selected.strip() == old.strip() or old.strip() in selected:
            newline = "\n" if original.endswith("\n") else ""
            source_file.write_text("".join(lines[:start - 1]) + replacement.rstrip("\n") + newline + "".join(lines[end:]), encoding="utf-8")
            return {"method": "line_range", "start_line": start, "end_line": end}
    count = original.count(old) if old else 0
    if count != 1:
        raise ValueError(f"ambiguous function replacement ({count} exact matches)")
    source_file.write_text(original.replace(old, replacement, 1), encoding="utf-8")
    return {"method": "exact_text", "occurrences": count}


def syntax_check(source_file, project):
    if source_file.suffix.lower() not in {".js", ".mjs", ".cjs"}:
        return True, ""
    try:
        proc = subprocess.run(["node", "--check", str(source_file)], cwd=project,
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"node syntax check failed: {exc}"
    return proc.returncode == 0, _tail(proc, 1200)


def ensure_jest(project, timeout):
    binary = find_jest_binary(str(project))
    if os.path.isfile(binary) and os.access(binary, os.X_OK):
        return True, binary, ""
    build = detect_build(str(project))
    if not build:
        return False, binary, "package.json not found"
    ok, reason = setup_deps(str(project), build["lockfile_mgr"], timeout)
    binary = find_jest_binary(str(project))
    if not ok or not os.path.exists(binary):
        return False, binary, reason or "Jest executable not found after dependency setup"
    return True, binary, ""


def run_jest(project, test_file, binary, timeout, report_path):
    relative = test_file.relative_to(project).as_posix()
    # Do not inherit a repository's native Jest configuration.  Some selected
    # projects use a restrictive testMatch (undici), while others intentionally
    # contain malformed/duplicate fixture package.json files (eslint).  A
    # per-suite config also ensures that deleted original tests and unrelated
    # fixtures cannot affect the benchmark result.
    config_dir = project / ".adverbug_jest_config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "jest.config.cjs"
    config_path.write_text(
        "module.exports = {\n"
        f"  rootDir: {json.dumps(str(project))},\n"
        f"  roots: [{json.dumps(str(test_file.parent))}],\n"
        f"  testMatch: [{json.dumps(str(test_file))}],\n"
        "  testEnvironment: 'node',\n"
        "  transform: {},\n"
        "  clearMocks: true,\n"
        "  restoreMocks: true,\n"
        "};\n",
        encoding="utf-8",
    )
    cmd = [binary, "--runTestsByPath", relative, "--runInBand", "--ci",
           "--passWithNoTests", "--config", str(config_path), "--json",
           "--outputFile", str(report_path)]
    try:
        proc = subprocess.run(cmd, cwd=project, capture_output=True, text=True, timeout=timeout,
                              env={**os.environ, "CI": "1",
                                   "NODE_OPTIONS": (os.environ.get("NODE_OPTIONS", "") + " --experimental-vm-modules").strip(),
                                   "JEST_CACHE_DIRECTORY": str(project / ".jest-cache")})
        status = parse_jest_report(report_path)
        return {"returncode": proc.returncode, "passed": proc.returncode == 0,
                "assertion_failed": status["assertion_failed"], "tests": status["tests"],
                "output": _tail(proc, 3000)}
    except subprocess.TimeoutExpired as exc:
        return {"returncode": -1, "passed": False, "assertion_failed": False,
                "tests": {}, "output": f"Jest timeout: {exc}"}
    finally:
        shutil.rmtree(config_dir, ignore_errors=True)


def parse_jest_report(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"tests": {}, "assertion_failed": False}
    tests, assertion_failed = {}, False
    for suite in data.get("testResults", []):
        for result in suite.get("assertionResults", []):
            name = result.get("fullName") or result.get("title", "")
            status = result.get("status", "unknown")
            tests[name] = status
            if status == "failed" and (result.get("failureMessages") or result.get("failureMessage")):
                assertion_failed = True
    return {"tests": tests, "assertion_failed": assertion_failed}


def evaluate_filter_model(entry, original_code, buggy_code, project, source_file,
                          agent, options, work_dir, model_label):
    tests = ""
    history = []
    test_rel = entry.get("test_file") or f".adverbug_generated/{model_label}.test.js"
    test_file = (project / test_rel).resolve()
    try:
        test_file.relative_to(project.resolve())
    except ValueError:
        return {"model": agent.model, "detected": False, "suite_generation_failed": True, "note": "test path escapes project"}
    test_file.parent.mkdir(parents=True, exist_ok=True)
    ok, binary, setup_error = ensure_jest(project, options.jest_install_timeout)
    if not ok:
        return {"model": agent.model, "detected": False, "suite_generation_failed": True, "note": setup_error}
    original_source = source_file.read_text(encoding="utf-8", errors="ignore")
    total_rounds = options.suite_retries + options.repair_rounds
    for round_number in range(total_rounds + 1):
        if not tests:
            tests = agent.generate_tests(entry, original_code, buggy_code)
        test_file.write_text(tests, encoding="utf-8")
        original_report = work_dir / f"{model_label}_original.json"
        original_run = run_jest(project, test_file, binary, options.jest_timeout, original_report)
        if not original_run["passed"]:
            feedback = "Original implementation did not pass the generated suite.\n" + original_run["output"]
        else:
            try:
                patch_info = patch_function(source_file, entry, buggy_code)
                valid, syntax_error = syntax_check(source_file, project)
                if not valid:
                    feedback = "Mutated source does not parse:\n" + syntax_error
                else:
                    buggy_report = work_dir / f"{model_label}_buggy.json"
                    buggy_run = run_jest(project, test_file, binary, options.jest_timeout, buggy_report)
                    source_file.write_text(original_source, encoding="utf-8")
                    if not buggy_run["passed"] and not buggy_run["assertion_failed"]:
                        # A TypeError/import/setup failure is a broken suite,
                        # not a reliable observation of the mutation.  Feed it
                        # back to the test model rather than accepting it.
                        feedback = "Buggy implementation caused a non-assertion Jest error; repair the suite:\n" + buggy_run["output"]
                    else:
                        detected = bool(buggy_run["assertion_failed"])
                        return {"model": agent.model, "detected": detected,
                                "suite_generation_failed": False, "repair_rounds": round_number,
                                "test_code": tests, "original_run": original_run,
                                "buggy_run": buggy_run, "patch": patch_info,
                                "note": "assertion_failure_on_buggy" if detected else "passed_on_buggy"}
            except Exception as exc:
                feedback = f"Could not apply or run mutated source: {exc}"
            finally:
                source_file.write_text(original_source, encoding="utf-8")
        history.append({"round": round_number, "feedback": feedback, "test_code": tests})
        if round_number >= total_rounds:
            break
        tests = agent.repair_tests(entry, original_code, buggy_code, tests, feedback)
    try:
        test_file.unlink()
    except OSError:
        pass
    return {"model": agent.model, "detected": False, "suite_generation_failed": True,
            "repair_rounds": total_rounds, "repair_history": history,
            "test_code": tests, "note": "suite_generation_failed"}


def process_entry(entry, source_root, options, bug_agent, judge, filter_agents, workspace):
    source_file_rel = Path(entry["src_file"])
    source_file = (workspace / source_file_rel).resolve()
    if not source_file.is_file():
        return {**entry, "status": "skipped", "reason": f"source file not found: {entry['src_file']}"}, []
    original_code = str(entry.get("code") or "")
    if not original_code:
        return {**entry, "status": "skipped", "reason": "empty function code"}, []
    source_original = source_file.read_text(encoding="utf-8", errors="ignore")
    try:
        delete_test_files_in_test_dirs(str(workspace))
    except Exception as exc:
        return {**entry, "status": "skipped", "reason": f"test cleanup failed: {exc}"}, []
    accepted, attempts = [], []
    previous_buggy_code = None
    previous_feedback = None
    specification = js_specification(entry)
    for attempt in range(options.attempts):
        if previous_buggy_code:
            bug = bug_agent.enhance_bug_prompt(
                original_code, previous_buggy_code, previous_feedback or "",
                specification, language="javascript")
        else:
            bug = bug_agent.init_bug_prompt(original_code, specification, language="javascript")
        if not bug or not bug.get("buggy_code"):
            attempts.append({"attempt": attempt, "status": "bug_generation_failed"})
            continue
        buggy_code = bug["buggy_code"]
        try:
            patch_function(source_file, entry, buggy_code)
            valid, syntax_error = syntax_check(source_file, workspace)
            source_file.write_text(source_original, encoding="utf-8")
            if not valid:
                attempts.append({"attempt": attempt, "status": "invalid_bug", "error": syntax_error})
                continue
        except Exception as exc:
            source_file.write_text(source_original, encoding="utf-8")
            attempts.append({"attempt": attempt, "status": "patch_failed", "error": str(exc)})
            continue
        suites = []
        for label, agent in zip(("filter_a", "filter_b"), filter_agents):
            suite = evaluate_filter_model(entry, original_code, buggy_code, workspace, source_file, agent, options, workspace, label)
            suites.append(suite)
        feedback = json.dumps(suites, ensure_ascii=False)
        # A missing/invalid suite is not evidence that a bug escaped.  Both
        # independent suites must have run successfully on the original
        # implementation before their non-detection can be counted.
        both_miss = all(
            not suite.get("detected")
            and not suite.get("suite_generation_failed")
            and suite.get("original_run", {}).get("passed", False)
            for suite in suites
        )
        if both_miss:
            judge_result = judge.validate(entry, original_code, buggy_code,
                                          "\n\n".join(s.get("test_code", "") for s in suites))
            if judge_result.get("is_valid_bug"):
                accepted_bug = {"bug_summary": bug.get("bug_summary", ""), "buggy_code": buggy_code,
                                "filter_feedback": feedback, "judge": judge_result,
                                "suites": suites}
                accepted.append(accepted_bug)
                attempts.append({"attempt": attempt, "status": "accepted", **accepted_bug, "suites": suites})
                break
            attempts.append({"attempt": attempt, "status": "judge_rejected", "judge": judge_result, "suites": suites})
        else:
            attempts.append({"attempt": attempt, "status": "detected_by_filter", "suites": suites})
            previous_buggy_code = buggy_code
            previous_feedback = feedback
        source_file.write_text(source_original, encoding="utf-8")
    source_file.write_text(source_original, encoding="utf-8")
    result = dict(entry)
    result.update({"status": "accepted" if accepted else "no_accepted_bug",
                   "buggy_code": [item["buggy_code"] for item in accepted],
                   "bug_summary": [item["bug_summary"] for item in accepted],
                   # Keep complete generated Jest sources directly extractable;
                   # filter_feedback remains in attempts for detailed reports.
                   "tests": [[suite.get("test_code", "") for suite in item.get("suites", [])]
                             for item in accepted],
                   "generated_tests": [item.get("suites", []) for item in accepted],
                   "attempts": len(attempts)})
    return result, attempts


def make_config(args, model):
    return LLMConfig(api_key=args.api_key, api_endpoint=args.api_endpoint, model_name=model)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate adversarial JavaScript bugs filtered by two Jest agents")
    parser.add_argument("--data-path", required=True)
    parser.add_argument("--project-root")
    parser.add_argument("--results-path", default="final_results_js.json")
    parser.add_argument("--stats-path", default="filter_stats_js.json")
    parser.add_argument("--work-dir", default=None)
    parser.add_argument("--bug-model", default="gpt-4")
    parser.add_argument("--judge-model", default="gpt-4")
    parser.add_argument("--filter-model-a", default="gpt-4")
    parser.add_argument("--filter-model-b", default="gpt-4")
    parser.add_argument("--api-key", default=os.getenv("LLM_API_KEY"))
    parser.add_argument("--api-endpoint", default=os.getenv("LLM_API_ENDPOINT"))
    parser.add_argument("--attempts", type=int, default=5)
    parser.add_argument("--suite-retries", type=int, default=2)
    parser.add_argument("--repair-rounds", type=int, default=5)
    parser.add_argument("--jest-timeout", type=int, default=180)
    parser.add_argument("--jest-install-timeout", type=int, default=900)
    parser.add_argument("--keep-workspaces", action="store_true")
    args = parser.parse_args(argv)
    data = json.loads(Path(args.data_path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("functions") or data.get("entries") or [data]
    options = argparse.Namespace(**vars(args))
    bug_agent = BugGenerationAgent(make_config(args, args.bug_model))
    judge = JavaScriptSemanticJudge(make_config(args, args.judge_model))
    filter_agents = [JavaScriptFilterAgent(make_config(args, model)) for model in (args.filter_model_a, args.filter_model_b)]
    results, stats = [], []
    base_work = Path(args.work_dir).resolve() if args.work_dir else Path(tempfile.mkdtemp(prefix="adverbug-js-"))
    base_work.mkdir(parents=True, exist_ok=True)
    try:
        for index, entry in enumerate(data):
            source_root = resolve_source_root(entry, Path(args.project_root).resolve() if args.project_root else None)
            if source_root is None:
                results.append({**entry, "status": "skipped", "reason": "project root not found"})
                continue
            workspace = base_work / f"entry-{index}"
            if workspace.exists():
                shutil.rmtree(workspace)
            try:
                copy_project(source_root, workspace)
                result, attempts = process_entry(entry, source_root, options, bug_agent, judge, filter_agents, workspace)
            except Exception as exc:
                result, attempts = ({**entry, "status": "failed", "reason": str(exc)}, [])
            results.append(result)
            stats.append({"index": index, "name": entry.get("name"), "attempts": attempts})
            print(f"[{index + 1}/{len(data)}] {entry.get('name', '')}: {result.get('status')}", flush=True)
    finally:
        if not args.keep_workspaces and not args.work_dir:
            shutil.rmtree(base_work, ignore_errors=True)
    results_path = Path(args.results_path)
    stats_path = Path(args.stats_path)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
