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
from functools import lru_cache
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
const candidateNames = new Set(
  (process.env.ADVER_TRACE_CANDIDATES || "").split(",").filter(Boolean)
);

function write(parts) {
  if (!output) return;
  try { fs.appendFileSync(output, parts.join("\t") + "\n"); } catch (_) {}
}

function record(name, file, line) {
  if (process.env.ADVER_TRACE_DISABLED === "1") return;
  const frames = String(new Error().stack || "").split("\n").slice(2);
  const caller = frames[1] || "";
  if (caller.includes(targetName) && (!targetFile || caller.includes(targetFile))) {
    write(["D", file, name, String(line)]);
  }
}

function inject(source, file) {
  if (file.includes("node_modules") || file === __filename ||
      source.includes("/*__adver_trace__*/")) return source;
  let result = source;
  const patterns = [
    /(function\s+([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{)/g,
    /((?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>\s*\{)/g,
    /((?:^|\n)\s*(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{)/g
  ];
  const excluded = new Set(["if", "for", "while", "switch", "catch", "with", "constructor"]);
  const edits = [];
  for (const pattern of patterns) {
    let match;
    while ((match = pattern.exec(source)) !== null) {
      const name = match[2];
      if (excluded.has(name) || (candidateNames.size && !candidateNames.has(name))) continue;
      const brace = match.index + match[1].lastIndexOf("{") + 1;
      const line = source.slice(0, match.index).split("\n").length;
      edits.push([brace, `\n/* istanbul ignore next */\n/*__adver_trace__*/;process.__adverTrace(${JSON.stringify(name)}, ${JSON.stringify(file)}, ${line});\n`]);
    }
  }
  const unique = new Map(edits.map(edit => [edit[0], edit]));
  edits.length = 0;
  edits.push(...unique.values());
  edits.sort((a, b) => b[0] - a[0]);
  for (const [position, text] of edits) result = result.slice(0, position) + text + result.slice(position);
  return result;
}

global.__adverTrace = { record };
process.__adverTrace = record;

function patchProject(directory) {
  let entries;
  try { entries = fs.readdirSync(directory, { withFileTypes: true }); } catch (_) { return; }
  for (const entry of entries) {
    const file = directory + "/" + entry.name;
    if (entry.isDirectory()) {
      if (!["node_modules", "test", "tests", ".git", "coverage"].includes(entry.name)) {
        patchProject(file);
      }
      continue;
    }
    if (!/\.(?:c?js|mjs|jsx)$/.test(entry.name)) continue;
    let source;
    try { source = fs.readFileSync(file, "utf8"); } catch (_) { continue; }
    const result = inject(source, file);
    if (result !== source) {
      try { fs.writeFileSync(file, result); } catch (_) {}
    }
  }
}

// Jest commonly executes transformed modules in a VM and bypasses
// Module._compile. Patch only candidate production functions in the disposable
// container checkout before Jest reads them; the marker makes this idempotent.
if (candidateNames.size) patchProject(projectRoot);

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


@lru_cache(maxsize=None)
def _project_function_locations(root: Path) -> dict[str, tuple[tuple[str, int], ...]]:
    """Conservative production function names mapped to container locations."""
    locations: dict[str, list[tuple[str, int]]] = {}
    patterns = (
        r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(",
        r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>",
        r"(?:^|\n)\s*(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{",
    )
    for path in root.rglob("*"):
        if path.suffix not in {".js", ".cjs", ".mjs", ".jsx"}:
            continue
        try:
            relative_parts = path.relative_to(root).parts
        except ValueError:
            continue
        if any(part in {"node_modules", "test", "tests", ".git", "coverage"}
               for part in relative_parts):
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pattern in patterns:
            for match in re.finditer(pattern, source, flags=re.MULTILINE):
                name = match.group(1)
                line = source.count("\n", 0, match.start(1)) + 1
                container_path = "/testbed/" + path.relative_to(root).as_posix()
                locations.setdefault(name, []).append((container_path, line))
    return {name: tuple(values) for name, values in locations.items()}


def _project_function_names(root: Path) -> set[str]:
    return set(_project_function_locations(root))


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
    start = int(item.get("start_line") or 0)
    end = int(item.get("end_line") or 0)
    if start > 0 and end >= start:
        body = "\n".join(source.splitlines()[start - 1:end])
    else:
        body = source[match.end():]
    keywords = {"if", "for", "while", "switch", "catch", "function", "return", "typeof", "new"}
    project_names = _project_function_names(
        Path(str(item.get("project_root") or ".")).resolve()
    )
    # Only member calls through relative project imports (plus this/self) are
    # accepted. This avoids treating e.g. external.decode() or buffer.set() as
    # project production functions merely because a same-named function exists
    # elsewhere in the checkout.
    project_aliases = {"this", "self"}
    for alias, module in re.findall(
        r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=.*?require\(\s*['\"]([^'\"]+)['\"]\s*\)",
        source,
    ):
        if module.startswith("."):
            project_aliases.add(alias)
    for alias, module in re.findall(
        r"\bimport\s+(?:\*\s+as\s+)?([A-Za-z_$][\w$]*)\s+from\s+['\"]([^'\"]+)['\"]",
        source,
    ):
        if module.startswith("."):
            project_aliases.add(alias)

    local_names: set[str] = set()
    for definition_pattern in (
        r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(",
        r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>",
    ):
        local_names.update(re.findall(definition_pattern, body))

    calls: set[str] = set()
    for owner, called in re.findall(
        r"\b([A-Za-z_$][\w$]*)\.([A-Za-z_$][\w$]*)\s*\(", body
    ):
        if owner in project_aliases and called in project_names:
            calls.add(called)
    for called in re.findall(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(", body):
        if (called not in keywords and called != str(item.get("name"))
                and (called in local_names or called in project_names)):
            calls.add(called)
    return calls


DynamicKey = tuple[str, str, int]


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/")


def _dynamic_candidates(path: Path) -> Counter[DynamicKey]:
    counts: Counter[DynamicKey] = Counter()
    if not path.is_file():
        return counts
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = raw.split("\t")
        if len(parts) == 4 and parts[0] == "D":
            try:
                line = int(parts[3])
            except ValueError:
                line = 0
            counts[(_normalize_path(parts[1]), parts[2], line)] += 1
        elif len(parts) == 2 and parts[0] == "D":
            # Read traces produced by the original prototype as unresolved
            # identities. New traces always contain file and source line.
            counts[("", parts[1], 0)] += 1
    return counts


def _metric(total: int, covered: int) -> dict[str, int | float | None]:
    return {"covered": covered, "total": total,
            "rate": covered / total if total else None}


def _function_metrics(entry: dict[str, Any], function_id: str) -> dict[str, Any]:
    function = (entry.get("fnMap") or {}).get(function_id) or {}
    location = function.get("loc") or {}
    try:
        start = int(location["start"]["line"])
        end = int(location["end"]["line"])
    except (KeyError, TypeError, ValueError):
        start = end = int(function.get("line") or 0)

    statement_hits = entry.get("s") or {}
    line_hits: dict[int, int] = {}
    for key, statement in (entry.get("statementMap") or {}).items():
        try:
            line = int(statement["start"]["line"])
        except (KeyError, TypeError, ValueError):
            continue
        if start <= line <= end:
            line_hits[line] = line_hits.get(line, 0) + int(statement_hits.get(str(key), 0) or 0)

    branch_hits: list[int] = []
    counters = entry.get("b") or {}
    for key, branch in (entry.get("branchMap") or {}).items():
        try:
            line = int(branch.get("line") or branch["loc"]["start"]["line"])
        except (KeyError, TypeError, ValueError):
            continue
        if start <= line <= end:
            branch_hits.extend(int(hit or 0) for hit in counters.get(str(key), []))
    return {
        "line": _metric(len(line_hits), sum(hit > 0 for hit in line_hits.values())),
        "branch": _metric(len(branch_hits), sum(hit > 0 for hit in branch_hits)),
        "first_line": start,
        "last_line": end,
        "execution_count": int((entry.get("f") or {}).get(str(function_id), 0) or 0),
    }


def _called_function_coverage(
    path: Path, dynamic_counts: Counter[DynamicKey], static_candidates: set[str],
    static_locations: dict[str, tuple[tuple[str, int], ...]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    dynamic_names = {name for _, name, _ in dynamic_counts}
    static_only_names = static_candidates - dynamic_names
    candidate_count = len(dynamic_counts) + len(static_only_names)
    aggregate: dict[str, Any] = {
        "line": {"covered": 0, "total": 0, "rate": None},
        "branch": {"covered": 0, "total": 0, "rate": None},
        "matched_function_count": 0,
        "unmatched_function_count": candidate_count,
    }
    executed = [
        {"file": file_name, "function": name, "first_line": line,
         "call_count": count, "coverage": None}
        for (file_name, name, line), count in sorted(dynamic_counts.items())
    ]
    static_only = [
        {"function": name, "coverage": None} for name in sorted(static_only_names)
    ]
    if not path.is_file() or not candidate_count:
        return executed, static_only, aggregate
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return executed, static_only, aggregate

    index: dict[tuple[str, str], list[tuple[int, dict[str, Any]]]] = {}
    for file_name, entry in report.items():
        if not isinstance(entry, dict):
            continue
        normalized_file = _normalize_path(str(file_name))
        for function_id, function in (entry.get("fnMap") or {}).items():
            name = str(function.get("name") or "")
            metrics = _function_metrics(entry, str(function_id))
            index.setdefault((normalized_file, name), []).append(
                (int(metrics["first_line"]), metrics)
            )

    seen: set[tuple[str, str, int]] = set()

    def add_coverage(identity: tuple[str, str, int], metrics: dict[str, Any]) -> None:
        if identity in seen:
            return
        seen.add(identity)
        for kind in ("line", "branch"):
            aggregate[kind]["covered"] += metrics[kind]["covered"]
            aggregate[kind]["total"] += metrics[kind]["total"]
        aggregate["matched_function_count"] += 1
        aggregate["unmatched_function_count"] -= 1

    for called in executed:
        file_name = str(called["file"])
        name = str(called["function"])
        candidates: list[tuple[int, dict[str, Any]]] = []
        anonymous_candidates: list[tuple[int, dict[str, Any]]] = []
        for (reported_file, reported_name), values in index.items():
            same_file = (not file_name or reported_file == file_name
                         or reported_file.endswith(file_name)
                         or file_name.endswith(reported_file))
            if same_file and reported_name == name:
                candidates.extend(values)
            elif same_file and reported_name.startswith("(anonymous_"):
                anonymous_candidates.extend(values)
        if not candidates and int(called["first_line"] or 0):
            trace_line = int(called["first_line"])
            candidates = [pair for pair in anonymous_candidates if pair[0] == trace_line]
        if not candidates:
            called["coverage_status"] = "not_present_in_istanbul_report"
            continue
        trace_line = int(called["first_line"] or 0)
        first_line, metrics = min(
            candidates, key=lambda pair: abs(pair[0] - trace_line) if trace_line else pair[0]
        )
        identity = (file_name, name, first_line)
        add_coverage(identity, metrics)
        called["coverage"] = metrics

    # Resolve static-only names against the loaded production modules. A name
    # is aggregated only when it identifies one Istanbul function uniquely;
    # ambiguous names remain explicit instead of silently inflating totals.
    for called in static_only:
        name = str(called["function"])
        matches = [
            (file_name, first_line, metrics)
            for (file_name, reported_name), values in index.items()
            if reported_name == name
            for first_line, metrics in values
        ]
        if not matches and static_locations:
            location_matches: list[tuple[str, int, dict[str, Any]]] = []
            for source_file, source_line in static_locations.get(name, ()):
                normalized_source = _normalize_path(source_file)
                for (file_name, reported_name), values in index.items():
                    same_file = (file_name == normalized_source
                                 or file_name.endswith(normalized_source)
                                 or normalized_source.endswith(file_name))
                    if not same_file or not reported_name.startswith("(anonymous_"):
                        continue
                    location_matches.extend(
                        (file_name, first_line, metrics)
                        for first_line, metrics in values
                        if first_line == source_line
                    )
            matches = location_matches
        if len(matches) != 1:
            called["coverage_status"] = (
                "ambiguous_istanbul_match" if matches
                else "not_present_in_istanbul_report"
            )
            called["match_count"] = len(matches)
            continue
        file_name, first_line, metrics = matches[0]
        called["file"] = file_name
        called["coverage"] = metrics
        add_coverage((file_name, name, first_line), metrics)
    for kind in ("line", "branch"):
        total = aggregate[kind]["total"]
        aggregate[kind]["rate"] = aggregate[kind]["covered"] / total if total else None
    return executed, static_only, aggregate


def _evaluate_one(item: dict[str, Any], index: int, image: str, output_dir: Path, timeout: int) -> dict[str, Any]:
    instance_id = _instance_id(index, item)
    run_dir = output_dir / "runs" / instance_id
    run_dir.mkdir(parents=True, exist_ok=True)
    static = _static_candidates(item)
    project_root = Path(str(item.get("project_root") or ".")).resolve()
    project_locations = _project_function_locations(project_root)
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
            "-e", "ADVER_TRACE_CANDIDATES=" + ",".join(sorted(static)),
            "-e", "ADVER_TRACE_COLLECT_LOADED=1",
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
    dynamic_names = {name for _, name, _ in dynamic}
    static_only_names = static - dynamic_names
    candidate_count = len(dynamic) + len(static_only_names)
    executed, static_only, coverage = _called_function_coverage(
        run_dir / "coverage" / "coverage-final.json", dynamic_counts, static,
        project_locations,
    )
    return {
        "instance_id": instance_id,
        "src_file": item.get("src_file"),
        "target_function": item.get("name"),
        "compile_pass": (run_dir / "syntax_exit_code.txt").read_text().strip() == "0" if (run_dir / "syntax_exit_code.txt").is_file() else False,
        "test_pass": (run_dir / "test_exit_code.txt").read_text().strip() == "0" if (run_dir / "test_exit_code.txt").is_file() else False,
        "static_called_functions": sorted(static),
        "executed_called_functions": executed,
        "static_only_called_functions": static_only,
        "called_function_coverage": {
            "candidate_scope": "static_union_dynamic_project_functions",
            "static_called_function_count": len(static),
            "executed_called_function_count": len(dynamic),
            "candidate_called_function_count": candidate_count,
            "covered_candidate_count": len(dynamic),
            "coverage_rate": len(dynamic) / candidate_count if candidate_count else None,
            "coverage_status": "measured" if candidate_count else "no_called_functions",
            "static_only_count": len(static_only_names),
            "dynamic_only_count": len(dynamic_names - static),
            "line": coverage["line"],
            "branch": coverage["branch"],
            "matched_function_count": coverage["matched_function_count"],
            "unmatched_function_count": coverage["unmatched_function_count"],
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
