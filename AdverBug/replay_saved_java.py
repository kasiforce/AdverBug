"""Resume Java adversarial filtering from complete candidates saved in filter_stats.json."""

import argparse
import copy
import json
import os
import time

from adver_dual import (
    DEFAULT_GPT_ENDPOINT,
    DEFAULT_QWEN_ENDPOINT,
    OPENROUTER_ENDPOINT,
    compile_test_suite,
    delete_test_files_in_test_dirs,
    evaluate_filter_model,
    maven_compile_diagnostics,
    mvn,
    parse_surefire_results,
    persist_outputs,
    read_text,
    set_src_code,
    test_class_name,
    uses_gpt_provider,
    write_text,
)
from filter_test_gen import FilterTestGenerationAgent
from llm_config import LLMConfig
from usage_tracker import usage_tracker
from valid_agent import ValidAgent


TESTBED = "/testbed"


def build_agents(args):
    gpt_key = os.getenv("GPT_API_KEY") or os.getenv("LLM_API_KEY")
    qwen_key = os.getenv("QWEN_API_KEY")
    if not gpt_key:
        raise RuntimeError("未设置 GPT_API_KEY（或兼容的 LLM_API_KEY）")

    gpt_endpoint = args.gpt_api_endpoint or os.getenv(
        "GPT_API_ENDPOINT", DEFAULT_GPT_ENDPOINT)
    model_b_uses_gpt = uses_gpt_provider(args.filter_model_b)
    qwen_endpoint = args.qwen_api_endpoint or os.getenv("QWEN_API_ENDPOINT")
    if not qwen_endpoint:
        qwen_endpoint = (OPENROUTER_ENDPOINT
                         if args.filter_model_b.startswith("qwen/")
                         else DEFAULT_QWEN_ENDPOINT)
    if not model_b_uses_gpt and not qwen_key:
        raise RuntimeError("未设置 QWEN_API_KEY")

    model_b_key = gpt_key if model_b_uses_gpt else qwen_key
    model_b_endpoint = gpt_endpoint if model_b_uses_gpt else qwen_endpoint
    return {
        "judge": ValidAgent(LLMConfig(gpt_key, gpt_endpoint, args.judge_model)),
        # Model A is only used if its saved, compilable suite now encounters a
        # runtime/infrastructure error that needs repair. It is never asked to
        # generate a fresh suite in resume mode.
        "model_a": FilterTestGenerationAgent(
            LLMConfig(gpt_key, gpt_endpoint, args.filter_model_a), 1),
        "model_b": FilterTestGenerationAgent(
            LLMConfig(model_b_key, model_b_endpoint, args.filter_model_b), 1),
    }


def replay_entry(entry, old_stat, agents):
    src_file = entry["src_file"]
    test_file = entry["test_file"]
    original_code = entry["code"]
    original_source = read_text(src_file)
    traces = []

    try:
        for candidate_index, old_attempt in enumerate(old_stat.get("attempts") or [], 1):
            bug_code = (old_attempt.get("bug_code_after_compile_fix")
                        or old_attempt.get("bug_code") or "")
            saved_a = ((old_attempt.get("model_a") or {}).get("generated_tests") or "")
            trace = {
                "candidate": candidate_index,
                "source_attempt": old_attempt.get("attempt", candidate_index),
                "bug_summary": old_attempt.get("bug_summary", ""),
            }
            if not bug_code or not saved_a:
                trace["outcome"] = "missing_saved_candidate"
                traces.append(trace)
                continue

            write_text(src_file, original_source)
            if not set_src_code(src_file, bug_code, original_code):
                trace["outcome"] = "patch_failed"
                traces.append(trace)
                continue

            compile_result = mvn(["compile"], timeout=1800, source_path=src_file)
            if compile_result.returncode != 0:
                trace["outcome"] = "saved_bug_compile_failed"
                trace["compile_error"] = maven_compile_diagnostics(
                    (compile_result.stdout or "") + (compile_result.stderr or ""))
                traces.append(trace)
                continue

            a_ok, a_tests, a_info = evaluate_filter_model(
                agents["model_a"], entry, bug_code, src_file, original_code,
                test_file, suite_retries=1, initial_tests=saved_a)
            a_info["model"] = agents["model_a"].model_name
            trace["model_a"] = a_info
            trace["model_a"]["generated_tests"] = a_tests
            if a_info.get("detected"):
                trace["outcome"] = "detected_by_model_a"
                traces.append(trace)
                continue
            if not a_ok:
                trace["outcome"] = "model_a_suite_failed"
                traces.append(trace)
                continue

            b_ok, b_tests, b_info = evaluate_filter_model(
                agents["model_b"], entry, bug_code, src_file, original_code,
                test_file, suite_retries=1)
            b_info["model"] = agents["model_b"].model_name
            trace["model_b"] = b_info
            trace["model_b"]["generated_tests"] = b_tests
            if b_info.get("detected"):
                trace["outcome"] = "detected_by_model_b"
                traces.append(trace)
                continue
            if not b_ok:
                trace["outcome"] = "model_b_suite_failed"
                traces.append(trace)
                continue

            validation = agents["judge"].validate(
                original_code, bug_code, (a_tests + "\n\n" + b_tests).strip())
            if not isinstance(validation, dict):
                validation = {"is_valid_bug": False,
                              "reason": "judge returned non-dict"}
            trace["validation"] = validation
            trace["outcome"] = ("accepted" if validation.get("is_valid_bug") is True
                                else "equivalent_mutation")
            traces.append(trace)
            if validation.get("is_valid_bug") is True:
                return True, {
                    "bug_code": bug_code,
                    "bug_summary": old_attempt.get("bug_summary", ""),
                    "suites": {"model_a": a_tests, "model_b": b_tests},
                    "filter_results": {"model_a": a_info, "model_b": b_info},
                    "validation": validation,
                }, traces
        return False, {}, traces
    finally:
        write_text(src_file, original_source)
        if test_file and os.path.exists(test_file):
            os.remove(test_file)


def main(args):
    agents = build_agents(args)
    with open(args.data_path, encoding="utf-8") as f:
        data = json.load(f)
    with open(args.resume_stats, encoding="utf-8") as f:
        old_stats = json.load(f)
    if len(data) != len(old_stats):
        raise ValueError(
            f"数据条目数与恢复统计不一致: {len(data)} != {len(old_stats)}")

    delete_test_files_in_test_dirs(TESTBED)
    finals, stats = [], []
    persist_outputs(args.results_path, args.stats_path, args.results_dir, finals, stats)

    for index, (entry, old_stat) in enumerate(zip(data, old_stats), 1):
        if entry.get("name") != old_stat.get("name"):
            raise ValueError(
                f"第 {index} 条名称不一致: {entry.get('name')} != {old_stat.get('name')}")
        print(f"\n===== replay [{index}/{len(data)}] {entry.get('name')} =====")
        usage_tracker.reset()
        started = time.perf_counter()
        try:
            accepted, accepted_data, traces = replay_entry(entry, old_stat, agents)
            status = "accepted" if accepted else (
                traces[-1]["outcome"] if traces else "no_saved_candidates")
            stats.append({
                "name": entry.get("name"),
                "status": status,
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "llm_usage": usage_tracker.summary(),
                "attempts": traces,
            })
            if accepted:
                result = copy.deepcopy(entry)
                result["buggy_code"] = [accepted_data["bug_code"]]
                result["tests"] = [accepted_data["suites"]["model_a"],
                                   accepted_data["suites"]["model_b"]]
                result["bug_summary"] = accepted_data["bug_summary"]
                result["flag"] = "dual_filter_pass"
                result["status"] = "accepted"
                result["filter_results"] = accepted_data["filter_results"]
                result["validation_result"] = accepted_data["validation"]
                result["filter_attempts"] = len(traces)
                result["resumed_from_saved_filter_stats"] = True
                finals.append(result)
        except Exception as exc:
            stats.append({
                "name": entry.get("name"),
                "status": "processing_error",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "llm_usage": usage_tracker.summary(),
            })
        persist_outputs(args.results_path, args.stats_path, args.results_dir,
                        finals, stats)

    print(f"\n恢复运行完成：接受 {len(finals)}/{len(data)} 条")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="从旧 filter_stats 恢复 Java 双模型过滤")
    parser.add_argument("--data-path", required=True)
    parser.add_argument("--resume-stats", required=True)
    parser.add_argument("--results-dir", default="/results")
    parser.add_argument("--results-path", default="/results/final_results.json")
    parser.add_argument("--stats-path", default="/results/filter_stats.json")
    parser.add_argument("--judge-model", default="gpt-5.6-luna")
    parser.add_argument("--filter-model-a", default="gpt-5.6-luna")
    parser.add_argument("--filter-model-b", default="gpt-5-nano")
    parser.add_argument("--gpt-api-endpoint", default=None)
    parser.add_argument("--qwen-api-endpoint", default=None)
    main(parser.parse_args())
