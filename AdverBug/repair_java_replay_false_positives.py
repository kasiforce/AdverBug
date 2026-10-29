"""Revalidate and repair false-positive Java filter suites from replay stats.

This is deliberately separate from the AdverBug generation/filter pipeline.
For every saved suite that claims to detect a candidate, it:

1. reproduces the failure on the saved buggy implementation;
2. only then runs the exact same suite on the original implementation;
3. if the original also fails, asks the suite's model to repair the test; and
4. keeps the bug only when the repaired suite passes on both implementations.

The input stats file is never overwritten.  The script writes a repaired copy
and a compact audit report.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
from typing import Any

import adver_dual as adver_runtime
from adver_dual import (
    DEFAULT_GPT_ENDPOINT,
    DEFAULT_QWEN_ENDPOINT,
    OPENROUTER_ENDPOINT,
    clean_surefire_reports,
    compile_test_suite,
    declared_class_names,
    maven_compile_diagnostics,
    mvn,
    parse_surefire_results,
    purge_stale_test_classes,
    read_text,
    run_compiled_test,
    set_src_code,
    test_class_name,
    uses_gpt_provider,
    write_text,
)
from filter_test_gen import FilterTestGenerationAgent
from llm_config import LLMConfig


def atomic_json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    temporary.replace(path)


def result_key(key: tuple[str, str]) -> str:
    class_name, test_name = key
    return f"{class_name}.{test_name}" if class_name else test_name


def failed_cases(results: dict[tuple[str, str], str]) -> list[str]:
    return sorted(
        result_key(key)
        for key, status in results.items()
        if status in {"failed", "error"}
    )


def run_saved_suite(test_file: str) -> dict[str, Any]:
    clean_surefire_reports()
    process = run_compiled_test(
        test_class_name(test_file), test_file=test_file, timeout=1800
    )
    parsed = parse_surefire_results()
    executed = {key: status for key, status in parsed.items() if status != "skipped"}
    failures = failed_cases(executed)
    output = ((process.stdout or "") + (process.stderr or ""))[-8000:]
    return {
        "returncode": process.returncode,
        "executed": len(executed),
        "results": {result_key(key): value for key, value in sorted(executed.items())},
        "failed_cases": failures,
        "clean": process.returncode == 0 and bool(executed) and not failures,
        "output": output,
    }


def compile_production(source_path: str) -> tuple[bool, str]:
    process = mvn(["compile"], timeout=1800, source_path=source_path)
    if process.returncode == 0:
        return True, ""
    output = (process.stdout or "") + (process.stderr or "")
    return False, maven_compile_diagnostics(output)


def compile_saved_suite(test_file: str, tests: str) -> tuple[bool, str]:
    """Compile the saved suite verbatim, without constructing an LLM client."""
    purge_stale_test_classes([test_class_name(test_file)] + declared_class_names(tests))
    write_text(test_file, tests)
    process = mvn(["test-compile"], timeout=1800, source_path=test_file)
    if process.returncode == 0:
        return True, ""
    output = (process.stdout or "") + (process.stderr or "")
    return False, maven_compile_diagnostics(output)


class OriginalTestRepairAgent(FilterTestGenerationAgent):
    """A no-tools repair client that only sees tests and execution errors."""

    def repair_false_positive(
        self,
        *,
        entry: dict[str, Any],
        tests: str,
        original_run: dict[str, Any],
    ) -> str:
        self.current_entry = entry
        prompt = f"""The Java test suite below fails when run against the correct original
implementation. Repair the test using only the test source and its execution
output. You have no repository, shell, file-search, source-code, specification,
or external-tool access. Do not claim to have inspected any code that is not
present in this request.

Strict acceptance requirements:
- the complete suite must compile and pass on the original implementation;
- keep meaningful coverage, but correct invalid expectations or test setup only
  when justified by the supplied execution output;
- do not disable, skip, weaken into a tautology, or catch-and-ignore a test;
- do not assert implementation-private details unless they are part of the
  observable contract.

Current tests:
```java
{tests}
```

Original-run failures:
```
{original_run.get('output', '')[-5000:]}
```

Return the complete Java compilation unit with no Markdown fences. Use only
the same JUnit version and imports already visible in the current tests.
"""
        repaired = self._call(
            "You repair Java tests using only the supplied test code and execution error.",
            prompt,
        )
        return self.normalize_tests(repaired, self._expected_class(entry))


class AgentPool:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self._agents: dict[str, OriginalTestRepairAgent] = {}

    def get(self, model: str) -> OriginalTestRepairAgent:
        if model in self._agents:
            return self._agents[model]

        if uses_gpt_provider(model):
            key = os.getenv("GPT_API_KEY") or os.getenv("LLM_API_KEY")
            endpoint = (
                self.args.gpt_api_endpoint
                or os.getenv("GPT_API_ENDPOINT")
                or DEFAULT_GPT_ENDPOINT
            )
        else:
            key = os.getenv("QWEN_API_KEY")
            endpoint = self.args.qwen_api_endpoint or os.getenv("QWEN_API_ENDPOINT")
            if not endpoint:
                endpoint = (
                    OPENROUTER_ENDPOINT if model.startswith("qwen/") else DEFAULT_QWEN_ENDPOINT
                )
        if not key:
            variable = "GPT_API_KEY/LLM_API_KEY" if uses_gpt_provider(model) else "QWEN_API_KEY"
            raise RuntimeError(f"model {model!r} requires {variable}")

        agent = OriginalTestRepairAgent(
            LLMConfig(key, endpoint, model),
            suite_retries=1,
            # Security boundary: this branch uses the plain chat-completions
            # call and never exposes Bash/repository exploration tools.
            use_production_tools=False,
        )
        self._agents[model] = agent
        return agent


def install_bug(
    source_path: str,
    original_source: str,
    original_code: str,
    buggy_code: str,
) -> tuple[bool, str]:
    write_text(source_path, original_source)
    if not set_src_code(source_path, buggy_code, original_code):
        return False, "could not replace the original method with the saved buggy method"
    return compile_production(source_path)


def install_original(source_path: str, original_source: str) -> tuple[bool, str]:
    write_text(source_path, original_source)
    return compile_production(source_path)


def process_detected_suite(
    *,
    entry: dict[str, Any],
    model_label: str,
    model_info: dict[str, Any],
    attempt: dict[str, Any],
    source_attempt: dict[str, Any] | None,
    pool: AgentPool,
    max_repairs: int,
) -> tuple[dict[str, Any], str | None]:
    source_path = entry["src_file"]
    test_file = entry["test_file"]
    original_code = entry["code"]
    source_attempt = source_attempt or {}
    buggy_code = (
        attempt.get("bug_code_after_compile_fix")
        or attempt.get("bug_code")
        or source_attempt.get("bug_code_after_compile_fix")
        or source_attempt.get("bug_code")
        or ""
    )
    tests = model_info.get("generated_tests") or ""
    report: dict[str, Any] = {
        "model_label": model_label,
        "model": model_info.get("model", ""),
        "initial_note": model_info.get("note", ""),
        "repair_attempts": [],
    }
    if not buggy_code or not tests:
        report["status"] = "missing_saved_bug_or_tests"
        return report, None

    source_original = read_text(source_path)
    test_existed = os.path.exists(test_file)
    test_original = read_text(test_file) if test_existed else None

    try:
        bug_ok, bug_error = install_bug(
            source_path, source_original, original_code, buggy_code
        )
        if not bug_ok:
            report.update(status="bug_compile_failed", error=bug_error)
            return report, None

        compile_ok, compile_error = compile_saved_suite(test_file, tests)
        if not compile_ok:
            report.update(status="saved_test_compile_failed", error=compile_error)
            return report, None

        buggy_run = run_saved_suite(test_file)
        report["initial_buggy_run"] = buggy_run
        if not buggy_run["failed_cases"]:
            report["status"] = (
                "not_reproduced_on_bug"
                if buggy_run["clean"]
                else "bug_suite_execution_failed"
            )
            return report, None

        original_ok, original_error = install_original(source_path, source_original)
        if not original_ok:
            report.update(status="original_compile_failed", error=original_error)
            return report, None
        original_run = run_saved_suite(test_file)
        report["initial_original_run"] = original_run
        if original_run["clean"]:
            report["status"] = "confirmed_differential_detection"
            report["differential_tests"] = buggy_run["failed_cases"]
            return report, tests
        report["false_positive_tests"] = original_run["failed_cases"]

        if max_repairs == 0:
            report["status"] = "false_positive_repair_skipped"
            return report, None

        # Construct the no-tools LLM client only after deterministic replay has
        # proved that the saved detection is a false positive.
        agent = pool.get(model_info.get("model") or pool.args.default_model)
        agent.current_entry = entry

        current_tests = tests
        current_original_run = original_run
        for repair_index in range(1, max_repairs + 1):
            # Repair while the checkout contains the original implementation so
            # repository exploration cannot accidentally learn only the mutant.
            install_original(source_path, source_original)
            repaired = agent.repair_false_positive(
                entry=entry,
                tests=current_tests,
                original_run=current_original_run,
            )
            repair_trace: dict[str, Any] = {"repair": repair_index}
            if not repaired or repaired == current_tests:
                repair_trace["status"] = "model_returned_no_change"
                report["repair_attempts"].append(repair_trace)
                break

            compile_ok, repaired, compile_error, auto_repairs = compile_test_suite(
                agent, test_file, repaired
            )
            repair_trace["auto_repairs"] = auto_repairs
            if not compile_ok:
                repair_trace.update(status="original_test_compile_failed", error=compile_error)
                report["repair_attempts"].append(repair_trace)
                current_tests = repaired
                current_original_run = {
                    "output": compile_error,
                    "clean": False,
                    "failed_cases": [],
                }
                continue

            current_original_run = run_saved_suite(test_file)
            repair_trace["original_run"] = current_original_run
            if not current_original_run["clean"]:
                repair_trace["status"] = "still_fails_on_original"
                report["repair_attempts"].append(repair_trace)
                current_tests = repaired
                continue

            bug_ok, bug_error = install_bug(
                source_path, source_original, original_code, buggy_code
            )
            if not bug_ok:
                repair_trace.update(status="bug_compile_failed", error=bug_error)
                report["repair_attempts"].append(repair_trace)
                break
            repaired_buggy_run = run_saved_suite(test_file)
            repair_trace["buggy_run"] = repaired_buggy_run
            if repaired_buggy_run["failed_cases"]:
                repair_trace["status"] = "repaired_differential_detection"
                report["repair_attempts"].append(repair_trace)
                report["status"] = "repaired_differential_detection"
                report["differential_tests"] = repaired_buggy_run["failed_cases"]
                return report, repaired

            if repaired_buggy_run["clean"]:
                repair_trace["status"] = "repaired_suite_passes_both"
                report["repair_attempts"].append(repair_trace)
                report["status"] = "repaired_suite_passes_both"
                return report, repaired

            repair_trace["status"] = "bug_suite_execution_failed_after_repair"
            report["repair_attempts"].append(repair_trace)
            report["status"] = "bug_suite_execution_failed_after_repair"
            return report, None

        report["status"] = "false_positive_repair_failed"
        return report, None
    finally:
        write_text(source_path, source_original)
        compile_production(source_path)
        if test_existed:
            write_text(test_file, test_original or "")
        elif os.path.exists(test_file):
            os.remove(test_file)


def main(args: argparse.Namespace) -> int:
    # Resolve every CLI path before changing into the project checkout.  This
    # keeps relative host invocations predictable while still making the
    # dataset's relative src_file/test_file paths resolve inside the testbed.
    args.data_path = str(Path(args.data_path).resolve())
    args.stats_path = str(Path(args.stats_path).resolve())
    args.output_stats = str(Path(args.output_stats).resolve())
    args.audit_path = str(Path(args.audit_path).resolve())
    stats_input_path = Path(args.stats_path)
    if args.candidate_stats:
        args.candidate_stats = str(Path(args.candidate_stats).resolve())
    else:
        replay_dir = stats_input_path.parent
        inferred_name = replay_dir.name.removesuffix("_replay")
        inferred = replay_dir.parent / inferred_name / "filter_stats.json"
        args.candidate_stats = str(inferred) if inferred.is_file() else ""
    testbed = Path(args.testbed).resolve()
    if not testbed.is_dir():
        raise FileNotFoundError(f"testbed does not exist: {testbed}")
    if args.max_repairs < 0:
        raise ValueError("max-repairs must be non-negative")
    # adver_dual's Maven/Surefire helpers use a module-level project root.
    # Point it at this standalone script's checkout instead of requiring the
    # historical hard-coded /testbed location.
    adver_runtime.TESTBED = str(testbed)
    os.environ["ADVER_TESTBED_ROOT"] = str(testbed)
    os.chdir(testbed)

    with Path(args.data_path).open(encoding="utf-8") as stream:
        entries = json.load(stream)
    with Path(args.stats_path).open(encoding="utf-8") as stream:
        original_stats = json.load(stream)
    candidate_stats = None
    if args.candidate_stats:
        with Path(args.candidate_stats).open(encoding="utf-8") as stream:
            candidate_stats = json.load(stream)
    if len(entries) != len(original_stats):
        raise ValueError(
            f"data/stats length mismatch: {len(entries)} != {len(original_stats)}"
        )

    repaired_stats = copy.deepcopy(original_stats)
    pool = AgentPool(args)
    audit: list[dict[str, Any]] = []

    for entry_index, (entry, stat) in enumerate(zip(entries, repaired_stats)):
        if args.entry_index is not None and entry_index != args.entry_index:
            continue
        if entry.get("name") != stat.get("name"):
            raise ValueError(
                f"entry {entry_index} name mismatch: "
                f"{entry.get('name')!r} != {stat.get('name')!r}"
            )
        print(f"\n===== [{entry_index + 1}/{len(entries)}] {entry.get('name')} =====")
        stat_requires_replay = False
        for attempt_index, attempt in enumerate(stat.get("attempts") or [], 1):
            candidate_number = attempt.get("candidate", attempt_index)
            if args.candidate is not None and candidate_number != args.candidate:
                continue
            source_attempt = None
            if candidate_stats is not None:
                candidates = candidate_stats[entry_index].get("attempts") or []
                wanted = attempt.get("source_attempt", attempt_index)
                source_attempt = next(
                    (item for item in candidates if item.get("attempt") == wanted),
                    candidates[wanted - 1] if isinstance(wanted, int) and 0 < wanted <= len(candidates) else None,
                )
            for model_label in ("model_a", "model_b"):
                model_info = attempt.get(model_label)
                if not isinstance(model_info, dict) or not model_info.get("detected"):
                    continue
                print(f"-- candidate {attempt_index}, {model_label}")
                report, validated_tests = process_detected_suite(
                    entry=entry,
                    model_label=model_label,
                    model_info=model_info,
                    attempt=attempt,
                    source_attempt=source_attempt,
                    pool=pool,
                    max_repairs=args.max_repairs,
                )
                report.update(
                    entry_index=entry_index,
                    name=entry.get("name"),
                    class_name=entry.get("class_name"),
                    candidate=attempt.get("candidate", attempt_index),
                )
                audit.append(report)
                model_info["differential_revalidation"] = report

                status = report["status"]
                if validated_tests is not None:
                    model_info["generated_tests"] = validated_tests
                    model_info["false_positives"] = (
                        report.get("initial_original_run", {}).get("failed_cases", [])
                    )
                    if status == "repaired_suite_passes_both":
                        model_info["detected"] = False
                        model_info["note"] = "passed_on_bug_after_false_positive_repair"
                        attempt["outcome"] = "passed_on_bug_after_false_positive_repair"
                        stat_requires_replay = True
                    elif status == "repaired_differential_detection":
                        model_info["note"] = "differentially_detected_after_false_positive_repair"
                elif status in {
                    "not_reproduced_on_bug",
                    "false_positive_repair_skipped",
                    "false_positive_repair_failed",
                }:
                    model_info["detected"] = False
                    model_info["note"] = status
                    attempt["outcome"] = status
                    stat_requires_replay = True

                atomic_json_dump(Path(args.output_stats), repaired_stats)
                atomic_json_dump(Path(args.audit_path), audit)

        if stat_requires_replay:
            stat["requires_filter_replay"] = True
        atomic_json_dump(Path(args.output_stats), repaired_stats)
        atomic_json_dump(Path(args.audit_path), audit)

    counts: dict[str, int] = {}
    for item in audit:
        status = item["status"]
        counts[status] = counts.get(status, 0) + 1
    print(f"\n完成：{len(audit)} 个检测套件，状态统计 {counts}")
    print(f"修复后统计：{args.output_stats}")
    print(f"审计报告：{args.audit_path}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="独立回放并修复 Java replay filter_stats 中的假阳性测试"
    )
    parser.add_argument("--data-path", required=True, help="与 stats 顺序一致的函数数据 JSON")
    parser.add_argument("--stats-path", required=True, help="输入 filter_stats.json（只读）")
    parser.add_argument(
        "--candidate-stats",
        default=None,
        help="保存 bug_code 的原始 stats；未指定时从相邻 adver_100 目录自动推断",
    )
    parser.add_argument("--output-stats", required=True, help="修复后的 stats 输出路径")
    parser.add_argument("--audit-path", required=True, help="差分验证审计报告输出路径")
    parser.add_argument("--testbed", default="/testbed", help="容器内项目根目录")
    parser.add_argument("--max-repairs", type=int, default=3)
    parser.add_argument("--entry-index", type=int, default=None, help="仅处理一个零基函数索引")
    parser.add_argument("--candidate", type=int, default=None, help="仅处理指定的候选编号（从 1 开始）")
    parser.add_argument("--default-model", default="gpt-5.6-luna")
    parser.add_argument("--gpt-api-endpoint", default=None)
    parser.add_argument("--qwen-api-endpoint", default=None)
    raise SystemExit(main(parser.parse_args()))
