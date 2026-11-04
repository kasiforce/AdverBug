#!/usr/bin/env python3
"""Prototype JavaScript direct-called-function coverage for Jest targets.

The runtime part uses a Node preload module that instruments simple named
function declarations and arrow functions.  It is intentionally conservative:
dynamic property dispatch, minified code, and functions whose syntax cannot be
recognized by the lightweight transformer are reported as unresolved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from eval_js import _safe_relative_path, _stage_item
except ModuleNotFoundError:  # package-style imports used by checks and notebooks
    from .eval_js import _safe_relative_path, _stage_item


EVAL_DIR = Path(__file__).resolve().parent
INSTANCE_SCRIPT = EVAL_DIR / "js_eval_container.sh"

TRACE_SOURCE = r'''
const fs = require("fs");
const Module = require("module");
const targetFile = process.env.ADVER_TRACE_TARGET_FILE || "";
const targetName = process.env.ADVER_TRACE_TARGET_NAME || "";
const output = process.env.ADVER_TRACE_OUTPUT || "";
const projectRoot = process.env.ADVER_TRACE_PROJECT_ROOT || process.cwd();

function write(parts) {
  if (!output) return;
  try { fs.appendFileSync(output, parts.join("\t") + "\n"); } catch (_) {}
}

function record(name) {
  const frames = String(new Error().stack || "").split("\n").slice(2);
  const caller = frames[1] || "";
  if (caller.includes(targetName)) write(["D", name]);
}

function inject(source, file) {
  if (file.includes("node_modules") || file === __filename) return source;
  let result = source;
  const patterns = [
    /(function\s+([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{)/g,
    /((?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>\s*\{)/g
  ];
  const edits = [];
  for (const pattern of patterns) {
    let match;
    while ((match = pattern.exec(source)) !== null) {
      const name = match[2];
      const brace = match.index + match[1].lastIndexOf("{") + 1;
      edits.push([brace, `\n;__adverTrace.record(${JSON.stringify(name)});\n`]);
    }
  }
  edits.sort((a, b) => b[0] - a[0]);
  for (const [position, text] of edits) result = result.slice(0, position) + text + result.slice(position);
  return result;
}

global.__adverTrace = { record };
const originalCompile = Module.prototype._compile;
Module.prototype._compile = function (content, filename) {
  if (filename.startsWith(projectRoot) && !filename.includes("node_modules")) {
    content = inject(content, filename);
  }
  return originalCompile.call(this, content, filename);
};
'''


def _instance_id(index: int, item: dict[str, Any]) -> str:
    digest = hashlib.sha1((str(item.get("src_file")) + str(item.get("name"))).encode()).hexdigest()[:10]
    return f"{index:04d}_{str(item.get('name', 'function'))[:35]}_{digest}"


def _source_path(item: dict[str, Any]) -> Path:
    return Path(str(item.get("project_root") or ".")) / _safe_relative_path(str(item.get("src_file", "")), "src_file")


def _static_candidates(item: dict[str, Any]) -> set[str]:
    path = _source_path(item)
    if not path.is_file():
        return set()
    source = path.read_text(encoding="utf-8", errors="replace")
    raw_name = str(item.get("name") or "")
    name = re.escape(raw_name)
    pattern = (r"(?:function\s+" + name
               + r"\s*\([^)]*\)|(?:const|let|var)\s+" + name
               + r"\s*=)[^{]*\{")
    match = re.search(pattern, source)
    if not match:
        return set()
    body = source[match.end():]
    keywords = {"if", "for", "while", "switch", "catch", "function", "return", "typeof", "new"}
    return {
        value for value in re.findall(r"\b([A-Za-z_$][\w$]*)\s*\(", body)
        if value not in keywords and value != str(item.get("name"))
    }


def _dynamic_candidates(path: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not path.is_file():
        return counts
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = raw.split("\t", 1)
        if len(parts) == 2 and parts[0] == "D":
            counts[parts[1]] += 1
    return counts


def _evaluate_one(item: dict[str, Any], index: int, image: str, output_dir: Path, timeout: int) -> dict[str, Any]:
    instance_id = _instance_id(index, item)
    run_dir = output_dir / "runs" / instance_id
    run_dir.mkdir(parents=True, exist_ok=True)
    static = _static_candidates(item)
    with tempfile.TemporaryDirectory(prefix="js-trace-input-") as stage_name, tempfile.TemporaryDirectory(prefix="js-trace-modules-") as trace_name:
        stage = Path(stage_name)
        trace = Path(trace_name)
        _stage_item(item, stage)
        (trace / "js_trace.js").write_text(TRACE_SOURCE, encoding="utf-8")
        command = [
            "docker", "run", "--rm", "--name", "adverbug-js-trace-" + instance_id,
            "-v", f"{stage}:/eval-input:ro", "-v", f"{run_dir}:/results",
            "-v", f"{trace}:/trace:ro", "-v", f"{INSTANCE_SCRIPT}:/eval/js_eval_container.sh:ro",
            "-e", "NODE_OPTIONS=--require=/trace/js_trace.js --experimental-vm-modules",
            "-e", "ADVER_TRACE_TARGET_FILE=/testbed/" + str(item["src_file"]).replace("\\", "/"),
            "-e", f"ADVER_TRACE_TARGET_NAME={item.get('name', '')}",
            "-e", "ADVER_TRACE_PROJECT_ROOT=/testbed",
            "-e", "ADVER_TRACE_OUTPUT=/results/calls.tsv",
            image, "bash", "/eval/js_eval_container.sh",
        ]
        started = time.monotonic()
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
            status = {"container_exit_code": completed.returncode}
            (run_dir / "docker.stdout.log").write_text(completed.stdout, encoding="utf-8")
            (run_dir / "docker.stderr.log").write_text(completed.stderr, encoding="utf-8")
        except subprocess.TimeoutExpired as error:
            subprocess.run(["docker", "rm", "-f", "adverbug-js-trace-" + instance_id], capture_output=True)
            status = {"container_exit_code": None, "timeout": True, "error": str(error)}
    dynamic_counts = _dynamic_candidates(run_dir / "calls.tsv")
    dynamic = set(dynamic_counts)
    candidates = static | dynamic
    return {
        "instance_id": instance_id,
        "src_file": item.get("src_file"),
        "target_function": item.get("name"),
        "compile_pass": (run_dir / "syntax_exit_code.txt").read_text().strip() == "0" if (run_dir / "syntax_exit_code.txt").is_file() else False,
        "test_pass": (run_dir / "test_exit_code.txt").read_text().strip() == "0" if (run_dir / "test_exit_code.txt").is_file() else False,
        "static_called_functions": sorted(static),
        "executed_called_functions": [{"function": key, "call_count": dynamic_counts[key]} for key in sorted(dynamic)],
        "called_function_coverage": {
            "static_called_function_count": len(static),
            "executed_called_function_count": len(dynamic),
            "candidate_called_function_count": len(candidates),
            "covered_candidate_count": len(dynamic),
            "coverage_rate": len(dynamic) / len(candidates) if candidates else None,
            "coverage_status": "measured" if candidates else "no_called_functions",
            "static_only_count": len(static - dynamic),
            "dynamic_only_count": len(dynamic - static),
        },
        "duration_seconds": time.monotonic() - started,
        **status,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-file", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args()
    args.data_file = args.data_file.resolve()
    args.output_dir = args.output_dir.resolve()
    items = json.loads(args.data_file.read_text(encoding="utf-8"))
    selected = items[args.start:args.start + args.limit if args.limit is not None else None]
    selected = [item for item in selected if str(item.get("target_type") or "").lower() != "source_file"]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for index, item in enumerate(selected, start=args.start):
        results.append(_evaluate_one(item, index, args.image, args.output_dir, args.timeout))
        print(f"[{len(results)}/{len(selected)}] {item.get('name')}", flush=True)
    output = args.output_dir / "dynamic_call_results.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"target_count": len(results), "output": str(output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
