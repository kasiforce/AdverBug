"""Replay one saved Java bug against one filtering/test-generation model.

This deliberately skips bug generation, the other filter model, and semantic
judging.  It is useful for comparing a model or a prompt change against an
already compiled candidate recorded in ``filter_stats.json``.
"""
import argparse
import json
import os
from pathlib import Path

from adver_dual import (
    DEFAULT_QWEN_ENDPOINT,
    OPENROUTER_ENDPOINT,
    evaluate_filter_model,
    read_text,
    set_src_code,
    test_class_name,
    write_text,
)
from filter_test_gen import FilterTestGenerationAgent
from llm_config import LLMConfig
from usage_tracker import usage_tracker


def saved_bug(stats_path: str, name: str, attempt: int) -> str:
    with open(stats_path, encoding="utf-8") as handle:
        records = json.load(handle)
    record = next((item for item in records if item.get("name") == name), None)
    if not record:
        raise ValueError(f"no saved result for {name!r}")
    attempts = record.get("attempts", [])
    if not 1 <= attempt <= len(attempts):
        raise ValueError(f"attempt must be in [1, {len(attempts)}]")
    bug = attempts[attempt - 1].get("bug_code_after_compile_fix", "").strip()
    if not bug:
        raise ValueError(f"attempt {attempt} has no compiled bug code")
    return bug


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one saved bug through one filter model")
    parser.add_argument("--data-path", required=True)
    parser.add_argument("--stats-path", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--index", type=int, required=True,
                        help="zero-based function index in data-path")
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--model", required=True)
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--no-tools", action="store_true",
                        help="send the supplied function context directly, without tool calls")
    parser.add_argument("--results-path", required=True)
    args = parser.parse_args()

    with open(args.data_path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not 0 <= args.index < len(data):
        raise ValueError("index is outside the input dataset")
    entry = data[args.index]
    if entry.get("name") != args.name:
        raise ValueError("name does not match the requested data index")

    uses_gpt = args.model.lower().startswith(("gpt-", "openai/gpt-"))
    key_name = "GPT_API_KEY" if uses_gpt else "QWEN_API_KEY"
    api_key = os.getenv(key_name)
    if not api_key:
        raise RuntimeError(f"{key_name} is not set")
    endpoint_env = "GPT_API_ENDPOINT" if uses_gpt else "QWEN_API_ENDPOINT"
    endpoint = args.endpoint or os.getenv(endpoint_env)
    if not endpoint:
        endpoint = ("https://api.agicto.cn/v1" if uses_gpt else
                    (OPENROUTER_ENDPOINT if args.model.startswith("qwen/")
                     else DEFAULT_QWEN_ENDPOINT))

    bug_code = saved_bug(args.stats_path, args.name, args.attempt)
    src_file = entry["src_file"]
    test_file = entry["test_file"]
    original_code = entry["code"]
    original_source = read_text(src_file)
    test_existed = os.path.exists(test_file)
    original_test = read_text(test_file) if test_existed else None

    agent = FilterTestGenerationAgent(
        LLMConfig(api_key, endpoint, args.model), suite_retries=1,
        use_production_tools=not args.no_tools)
    usage_tracker.reset()
    try:
        if not set_src_code(src_file, bug_code, original_code):
            raise RuntimeError("saved bug could not be uniquely applied to source")
        undetected, tests, info = evaluate_filter_model(
            agent, entry, bug_code, src_file, original_code, test_file, suite_retries=1)
        result = {
            "name": args.name,
            "saved_attempt": args.attempt,
            "model": args.model,
            "tools_enabled": not args.no_tools,
            "undetected": undetected,
            "filter_result": info,
            "generated_tests": tests,
            "llm_usage": usage_tracker.summary(),
        }
    finally:
        write_text(src_file, original_source)
        if test_existed:
            write_text(test_file, original_test)
        elif os.path.exists(test_file):
            os.remove(test_file)

    output = Path(args.results_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "generated_tests"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
