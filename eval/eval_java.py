#!/usr/bin/env python3
"""Evaluate generated Java tests in isolated Docker containers.

Each benchmark item is compiled and executed in a fresh container.  Its JaCoCo
execution data is copied to the host.  After all items have finished, the exec
files are merged and file coverage is calculated from the union of JaCoCo
probes, never by averaging percentages.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

try:
    # tree_sitter_languages ships a Java grammar and performs syntax-only
    # parsing without resolving imports, types, or project dependencies.
    from tree_sitter_languages import get_parser as _get_tree_sitter_parser
except ImportError:  # Reported explicitly in the output instead of aborting evaluation.
    _get_tree_sitter_parser = None


EVAL_DIR = Path(__file__).resolve().parent
INSTANCE_SCRIPT = EVAL_DIR / "java_eval_container.sh"
MERGE_SCRIPT = EVAL_DIR / "java_merge_coverage.sh"
DEFAULT_JACOCO_VERSION = "0.8.14"


def _safe_relative_path(value: str, field: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} must be a safe project-relative path: {value!r}")
    return path


def _safe_name(value: str, max_length: int = 70) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "item"
    return cleaned[:max_length]


def _instance_id(index: int, item: dict[str, Any]) -> str:
    identity = "|".join(
        str(item.get(key, ""))
        for key in ("src_file", "class_name", "method_key", "name", "start_line")
    )
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:10]
    return f"{index:04d}_{_safe_name(str(item.get('name', 'method')), 35)}_{digest}"


def _module_dir(src_file: str) -> str:
    marker = "/src/main/java/"
    normalized = src_file.replace("\\", "/")
    if marker in f"/{normalized}":
        prefix = f"/{normalized}".split(marker, 1)[0].lstrip("/")
        return prefix or "."
    return "."


def _jacoco_file_key(src_file: str) -> str:
    normalized = src_file.replace("\\", "/")
    marker = "src/main/java/"
    if marker in normalized:
        return normalized.split(marker, 1)[1]
    return normalized


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _atomic_json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _counter(element: ET.Element, counter_type: str) -> tuple[int, int]:
    counter = element.find(f"./counter[@type='{counter_type}']")
    if counter is None:
        return 0, 0
    missed = int(counter.attrib.get("missed", 0))
    covered = int(counter.attrib.get("covered", 0))
    return missed + covered, covered


def _coverage(total: int, covered: int) -> dict[str, Any]:
    return {
        "total": total,
        "covered": covered,
        "rate": covered / total if total else 0.0,
    }


def _coverage_pair(element: ET.Element) -> dict[str, Any]:
    line_total, line_covered = _counter(element, "LINE")
    branch_total, branch_covered = _counter(element, "BRANCH")
    return {
        "line": _coverage(line_total, line_covered),
        "branch": _coverage(branch_total, branch_covered),
    }


def _sourcefile_elements(root: ET.Element) -> Iterable[tuple[str, ET.Element]]:
    for package in root.findall("package"):
        package_name = package.attrib.get("name", "")
        for source in package.findall("sourcefile"):
            name = source.attrib.get("name", "")
            yield f"{package_name}/{name}".lstrip("/"), source


def parse_instance_coverage(xml_path: Path, item: dict[str, Any]) -> dict[str, Any]:
    """Read target method and target source-file coverage from one run."""
    empty = {
        "report_found": False,
        "target_file": None,
        "target_function": None,
    }
    if not xml_path.is_file():
        return empty

    try:
        root = ET.parse(xml_path).getroot()
    except (ET.ParseError, OSError) as error:
        return {**empty, "parse_error": str(error)}

    file_key = _jacoco_file_key(str(item.get("src_file", "")))
    target_file = None
    for key, source in _sourcefile_elements(root):
        if key == file_key:
            target_file = {"file_key": key, **_coverage_pair(source)}
            break

    requested_name = str(item.get("name", ""))
    class_name = str(item.get("class_name") or "")
    if requested_name == class_name or str(item.get("type", "")).lower() == "constructor":
        requested_name = "<init>"

    full_class = str(item.get("full_class_name") or "").replace(".", "/")
    start_line = int(item.get("start_line") or 0)
    end_line = int(item.get("end_line") or 0)
    candidates: list[dict[str, Any]] = []
    for package in root.findall("package"):
        for cls in package.findall("class"):
            internal_name = cls.attrib.get("name", "")
            source_key = f"{package.attrib.get('name', '')}/{cls.attrib.get('sourcefilename', '')}".lstrip("/")
            if source_key != file_key:
                continue
            if full_class and internal_name != full_class and not internal_name.startswith(full_class + "$"):
                # Extracted metadata names a nested class as package.SimpleName,
                # while JaCoCo uses package/Outer$SimpleName.  Match the nested
                # leaf name within the same package as a fallback.
                requested_package, _, requested_simple = full_class.rpartition("/")
                internal_package, _, internal_simple = internal_name.rpartition("/")
                if not (
                    class_name
                    and requested_package == internal_package
                    and requested_simple == class_name
                    and internal_simple.split("$")[-1] == class_name
                ):
                    continue
            if not full_class and class_name and internal_name.rsplit("/", 1)[-1].split("$", 1)[0] != class_name:
                continue
            for method in cls.findall("method"):
                if method.attrib.get("name") != requested_name:
                    continue
                method_line = int(method.attrib.get("line", 0) or 0)
                candidates.append(
                    {
                        "class": internal_name.replace("/", "."),
                        "method": method.attrib.get("name"),
                        "descriptor": method.attrib.get("desc"),
                        "first_line": method_line,
                        **_coverage_pair(method),
                    }
                )

    line_matches = [
        candidate
        for candidate in candidates
        if start_line and end_line and start_line <= candidate["first_line"] <= end_line
    ]
    selected = line_matches or candidates
    function_coverage = None
    if selected:
        line_total = sum(entry["line"]["total"] for entry in selected)
        line_covered = sum(entry["line"]["covered"] for entry in selected)
        branch_total = sum(entry["branch"]["total"] for entry in selected)
        branch_covered = sum(entry["branch"]["covered"] for entry in selected)
        function_coverage = {
            "line": _coverage(line_total, line_covered),
            "branch": _coverage(branch_total, branch_covered),
            "matched_methods": selected,
            "ambiguous_match": len(selected) != 1,
        }

    return {
        "report_found": True,
        "target_file": target_file,
        "target_function": function_coverage,
    }


def parse_junit_reports(report_dir: Path) -> dict[str, Any]:
    totals = {"total": 0, "failures": 0, "errors": 0, "skipped": 0}
    xml_attributes = {
        "total": "tests",
        "failures": "failures",
        "errors": "errors",
        "skipped": "skipped",
    }
    report_count = 0
    parse_errors: list[str] = []
    if report_dir.is_dir():
        for report in report_dir.rglob("TEST-*.xml"):
            try:
                root = ET.parse(report).getroot()
                suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
                for suite in suites:
                    for key, attribute in xml_attributes.items():
                        totals[key] += int(suite.attrib.get(attribute, 0))
                report_count += 1
            except (ET.ParseError, OSError, ValueError) as error:
                parse_errors.append(f"{report.name}: {error}")

    passed = max(0, totals["total"] - totals["failures"] - totals["errors"] - totals["skipped"])
    return {
        **totals,
        "passed": passed,
        "pass_rate": passed / totals["total"] if totals["total"] else 0.0,
        "report_count": report_count,
        "parse_errors": parse_errors,
    }


def _read_int(path: Path, default: int | None = None) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return default


def _stage_item(item: dict[str, Any], stage_dir: Path) -> None:
    test_path = _safe_relative_path(str(item.get("test_file", "")), "test_file")
    generated_tests = item.get("generated_tests") or []
    code = "\n\n".join(str(part) for part in generated_tests if str(part).strip()).strip()
    if not code:
        raise ValueError("generated_tests is empty")
    _write_text(stage_dir / "files" / Path(*test_path.parts), code + "\n")
    _write_text(stage_dir / "test_file.txt", test_path.as_posix() + "\n")

    for config in item.get("generated_config_files") or []:
        if not isinstance(config, dict) or not config.get("path"):
            continue
        config_path = _safe_relative_path(str(config["path"]), "generated_config_files.path")
        _write_text(stage_dir / "files" / Path(*config_path.parts), str(config.get("code", "")))


def analyse_java_syntax(item: dict[str, Any]) -> dict[str, Any]:
    """Parse the complete generated test as a Java compilation unit.

    This deliberately does not resolve imports, types, or dependencies.  Those
    belong to the separate Maven compilation metric.
    """
    generated_tests = item.get("generated_tests") or []
    code = "\n\n".join(str(part) for part in generated_tests if str(part).strip()).strip()
    result: dict[str, Any] = {
        "parser": "tree-sitter-java",
        "has_code": bool(code),
        "correct": False,
    }
    if not code:
        result.update(error_type="EmptyGeneratedTest", error_message="generated_tests is empty")
        return result
    if _get_tree_sitter_parser is None:
        result.update(
            parser_available=False,
            error_type="ParserUnavailable",
            error_message="Install the Python package 'tree-sitter-languages' to calculate Java syntax correctness",
        )
        return result

    result["parser_available"] = True
    try:
        parser = _get_tree_sitter_parser("java")
        tree = parser.parse(code.encode("utf-8"))
        result["correct"] = not tree.root_node.has_error
        if not result["correct"]:
            result.update(
                error_type="SyntaxError",
                error_message="tree-sitter-java reported an ERROR node",
            )
    except Exception as error:  # javalang exposes several lexer/parser error classes.
        message = str(error) or getattr(error, "description", None) or repr(error)
        result.update(
            error_type=type(error).__name__,
            error_message=str(message)[:1000],
        )
    return result


def _copy_if_present(source: Path, destination: Path) -> str | None:
    if not source.is_file() or source.stat().st_size == 0:
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination.as_posix()


def evaluate_instance(
    *,
    image: str,
    item: dict[str, Any],
    index: int,
    output_dir: Path,
    jacoco_version: str,
    timeout: int,
    keep_logs: bool,
    keep_individual_xml: bool,
) -> dict[str, Any]:
    instance_id = _instance_id(index, item)
    container_suffix = hashlib.sha1(str(output_dir).encode("utf-8")).hexdigest()[:8]
    container_name = f"adverbug-eval-{container_suffix}-{instance_id}"[:120]
    started = time.monotonic()
    evaluation: dict[str, Any] = {
        "instance_id": instance_id,
        "compile_pass": False,
        "test_pass": False,
        "failure_stage": None,
    }

    with tempfile.TemporaryDirectory(prefix="java-eval-input-") as stage_name, tempfile.TemporaryDirectory(
        prefix="java-eval-output-"
    ) as run_name:
        stage_dir = Path(stage_name)
        run_dir = Path(run_name)
        try:
            _stage_item(item, stage_dir)
        except (ValueError, OSError) as error:
            evaluation.update(failure_stage="input", failure_message=str(error))
            evaluation["duration_seconds"] = time.monotonic() - started
            return evaluation

        command = [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "-v",
            f"{stage_dir}:/eval-input:ro",
            "-v",
            f"{run_dir}:/results",
            "-v",
            f"{INSTANCE_SCRIPT}:/eval/java_eval_container.sh:ro",
            "-e",
            f"JACOCO_VERSION={jacoco_version}",
            image,
            "bash",
            "/eval/java_eval_container.sh",
        ]
        try:
            completed = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
            evaluation["container_exit_code"] = completed.returncode
        except subprocess.TimeoutExpired as error:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                text=True,
                capture_output=True,
                check=False,
            )
            evaluation.update(failure_stage="timeout", failure_message=f"Exceeded {timeout} seconds")
            completed = None
            captured = (error.stdout or "") + "\n" + (error.stderr or "")
            _write_text(output_dir / "logs" / f"{instance_id}.log", captured)
        except KeyboardInterrupt:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                text=True,
                capture_output=True,
                check=False,
            )
            raise

        compile_exit = _read_int(run_dir / "compile_exit_code.txt")
        test_exit = _read_int(run_dir / "test_exit_code.txt")
        evaluation["compile_exit_code"] = compile_exit
        evaluation["test_exit_code"] = test_exit
        evaluation["compile_pass"] = compile_exit == 0

        junit = parse_junit_reports(run_dir / "reports")
        evaluation["test_summary"] = junit
        evaluation["test_pass"] = bool(
            compile_exit == 0
            and test_exit == 0
            and junit["total"] > 0
            and junit["passed"] > 0
            and junit["failures"] == 0
            and junit["errors"] == 0
        )

        if evaluation["failure_stage"] is None:
            if compile_exit is None:
                evaluation["failure_stage"] = "infrastructure"
            elif compile_exit != 0:
                evaluation["failure_stage"] = "compile"
            elif test_exit is None:
                evaluation["failure_stage"] = "test_infrastructure"
            elif test_exit != 0 or not evaluation["test_pass"]:
                evaluation["failure_stage"] = "test"

        exec_destination = output_dir / "exec" / f"{instance_id}.exec"
        saved_exec = _copy_if_present(run_dir / "jacoco.exec", exec_destination)
        evaluation["jacoco_exec"] = (
            str(exec_destination.relative_to(output_dir)) if saved_exec else None
        )

        instance_xml = run_dir / "jacoco.xml"
        evaluation["coverage"] = parse_instance_coverage(instance_xml, item)
        if keep_individual_xml and instance_xml.is_file():
            xml_destination = output_dir / "individual_xml" / f"{instance_id}.xml"
            _copy_if_present(instance_xml, xml_destination)
            evaluation["jacoco_xml"] = str(xml_destination.relative_to(output_dir))

        should_keep_log = (
            keep_logs
            or not evaluation["compile_pass"]
            or not evaluation["test_pass"]
            or not evaluation["jacoco_exec"]
        )
        if should_keep_log:
            log_parts: list[str] = []
            if completed is not None:
                log_parts.extend(
                    [
                        "=== docker stdout ===\n" + completed.stdout,
                        "=== docker stderr ===\n" + completed.stderr,
                    ]
                )
            for name in ("compile.log", "test.log", "coverage.log"):
                log_path = run_dir / name
                if log_path.is_file():
                    log_parts.append(f"=== {name} ===\n" + log_path.read_text(encoding="utf-8", errors="replace"))
            destination = output_dir / "logs" / f"{instance_id}.log"
            _write_text(destination, "\n".join(log_parts))
            evaluation["log"] = str(destination.relative_to(output_dir))

    evaluation["duration_seconds"] = time.monotonic() - started
    return evaluation


def _module_slug(module: str) -> str:
    digest = hashlib.sha1(module.encode("utf-8")).hexdigest()[:8]
    return f"{_safe_name(module.replace('/', '_'), 45)}_{digest}"


def _file_slug(src_file: str) -> str:
    digest = hashlib.sha1(src_file.encode("utf-8")).hexdigest()[:10]
    return f"{_safe_name(Path(src_file).stem, 40)}_{digest}"


def _write_merge_manifests(
    output_dir: Path,
    results: list[dict[str, Any]],
    kind: str,
) -> tuple[list[str], dict[str, str]]:
    exec_paths: list[str] = []
    modules: dict[str, str] = {}
    file_group_lines: list[str] = []
    for item in results:
        evaluation = item.get("evaluation") or {}
        include = evaluation.get("jacoco_exec") and (
            kind == "all_executed" or evaluation.get("test_pass") is True
        )
        if include:
            exec_path = str(evaluation["jacoco_exec"])
            exec_paths.append(exec_path)
            src_file = str(item.get("src_file", ""))
            if src_file:
                file_group_lines.append(
                    "\t".join(
                        (_file_slug(src_file), _module_dir(src_file), src_file, exec_path)
                    )
                )
        src_file = str(item.get("src_file", ""))
        if evaluation and src_file:
            module = _module_dir(src_file)
            modules[module] = _module_slug(module)

    _write_text(output_dir / f"{kind}_exec_manifest.txt", "\n".join(exec_paths) + ("\n" if exec_paths else ""))
    _write_text(
        output_dir / f"{kind}_file_groups.tsv",
        "\n".join(file_group_lines) + ("\n" if file_group_lines else ""),
    )
    module_lines = [f"{slug}\t{module}" for module, slug in sorted(modules.items())]
    _write_text(output_dir / "module_manifest.tsv", "\n".join(module_lines) + "\n")
    return exec_paths, modules


def merge_coverage(
    *,
    image: str,
    output_dir: Path,
    results: list[dict[str, Any]],
    kind: str,
    jacoco_version: str,
    timeout: int,
) -> dict[str, Any]:
    exec_paths, modules = _write_merge_manifests(output_dir, results, kind)
    status: dict[str, Any] = {
        "kind": kind,
        "exec_count": len(exec_paths),
        "success": False,
        "modules": modules,
        "file_group_count": len(
            {
                str(item.get("src_file"))
                for item in results
                if item.get("src_file")
                and (item.get("evaluation") or {}).get("jacoco_exec")
                and (
                    kind == "all_executed"
                    or (item.get("evaluation") or {}).get("test_pass") is True
                )
            }
        ),
    }
    if not exec_paths:
        status["error"] = "No JaCoCo exec files were eligible for merging"
        return status

    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{output_dir}:/results",
        "-v",
        f"{MERGE_SCRIPT}:/eval/java_merge_coverage.sh:ro",
        "-e",
        f"JACOCO_VERSION={jacoco_version}",
        "-e",
        f"COVERAGE_KIND={kind}",
        image,
        "bash",
        "/eval/java_merge_coverage.sh",
    ]
    try:
        completed = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
        status["container_exit_code"] = completed.returncode
        status["success"] = completed.returncode == 0
        if completed.returncode != 0:
            status["error"] = (completed.stderr or completed.stdout)[-4000:]
        _write_text(
            output_dir / "coverage" / kind / "merge.log",
            "=== stdout ===\n" + completed.stdout + "\n=== stderr ===\n" + completed.stderr,
        )
    except subprocess.TimeoutExpired:
        status["error"] = f"Coverage merge exceeded {timeout} seconds"
    return status


def collect_merged_file_coverage(
    output_dir: Path,
    results: list[dict[str, Any]],
    kind: str,
    modules: dict[str, str],
) -> dict[str, Any]:
    wanted_files: dict[str, str] = {}
    for item in results:
        if not item.get("evaluation"):
            continue
        src_file = str(item.get("src_file", ""))
        if src_file:
            wanted_files[src_file] = _module_dir(src_file)

    collected: dict[str, Any] = {}
    for src_file, module in wanted_files.items():
        slug = _file_slug(src_file)
        xml_path = output_dir / "coverage" / kind / "files" / f"{slug}.xml"
        if not xml_path.is_file():
            collected[src_file] = {"report_found": False, "module": module}
            continue
        try:
            root = ET.parse(xml_path).getroot()
            by_key = dict(_sourcefile_elements(root))
        except (ET.ParseError, OSError) as error:
            collected[src_file] = {
                "report_found": False,
                "module": module,
                "parse_error": str(error),
            }
            continue
        key = _jacoco_file_key(src_file)
        element = by_key.get(key)
        collected[src_file] = {
            "report_found": element is not None,
            "module": module,
            "file_key": key,
            **(_coverage_pair(element) if element is not None else {}),
        }
    return collected


def _build_image(dockerfile: Path, context: Path, image: str) -> None:
    subprocess.run(
        ["docker", "build", "-t", image, "-f", str(dockerfile), str(context)],
        check=True,
    )


def evaluate_dataset(args: argparse.Namespace) -> dict[str, Any]:
    data_file = args.data_file.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    evaluated_path = output_dir / "evaluated_results.json"

    source_items = json.loads(data_file.read_text(encoding="utf-8"))
    if not isinstance(source_items, list):
        raise ValueError("The generated-test JSON must contain a top-level list")
    source_target_count = len(source_items)
    if args.only_successfully_generated:
        source_items = [
            item
            for item in source_items
            if (item.get("mini_swe_agent") or {}).get("exit_status") == "Submitted"
        ]
        print(
            f"Generation filter: evaluating {len(source_items)}/{source_target_count} "
            "items with exit_status=Submitted",
            flush=True,
        )
    skipped_generation_count = source_target_count - len(source_items)

    if args.resume and evaluated_path.is_file():
        previous = json.loads(evaluated_path.read_text(encoding="utf-8"))
        if isinstance(previous, list):
            # Refresh generated tests and benchmark metadata from the current
            # input while retaining completed evaluation records.  This is
            # important when one test-generation result has been regenerated
            # and only that instance needs to be evaluated again.
            previous_by_instance_id = {
                (item.get("mini_swe_agent") or {}).get("instance_id"): item
                for item in previous
                if (item.get("mini_swe_agent") or {}).get("instance_id")
            }
            results = []
            reused = 0
            for source_item in source_items:
                refreshed = dict(source_item)
                instance_id = (source_item.get("mini_swe_agent") or {}).get("instance_id")
                previous_item = previous_by_instance_id.get(instance_id) or {}
                if previous_item.get("evaluation"):
                    refreshed["evaluation"] = previous_item["evaluation"]
                    reused += 1
                results.append(refreshed)
            print(f"Resume: matched {reused}/{len(source_items)} prior evaluations", flush=True)
        else:
            raise ValueError("Cannot resume: evaluated_results.json is not a list")
    else:
        results = source_items

    # Syntax is independent of Docker and is therefore calculated for every
    # benchmark target, including empty generations and items outside a smoke
    # test's --start/--limit range.
    for item in results:
        item["syntax_evaluation"] = analyse_java_syntax(item)
    _atomic_json_dump(evaluated_path, results)

    stop = len(results) if args.limit is None else min(len(results), args.start + args.limit)
    pending: list[int] = []
    for index in range(args.start, stop):
        item = results[index]
        existing = item.get("evaluation") or {}
        existing_exec = existing.get("jacoco_exec")
        if args.resume and not args.redo_existing and existing.get("compile_exit_code") is not None:
            finished_without_coverage = existing.get("compile_pass") is False
            finished_with_coverage = bool(
                existing_exec and (output_dir / str(existing_exec)).is_file()
            )
            if finished_without_coverage or finished_with_coverage:
                print(f"[{index + 1}/{len(results)}] resume: {item.get('name')}", flush=True)
                continue
        pending.append(index)

    def run_index(index: int) -> tuple[int, dict[str, Any]]:
        item = results[index]
        print(
            f"[{index + 1}/{len(results)}] evaluating {item.get('name')} in a fresh container",
            flush=True,
        )
        return index, evaluate_instance(
            image=args.image,
            item=item,
            index=index,
            output_dir=output_dir,
            jacoco_version=args.jacoco_version,
            timeout=args.timeout,
            keep_logs=args.keep_logs,
            keep_individual_xml=args.keep_individual_xml,
        )

    if args.workers == 1:
        completed_instances = map(run_index, pending)
        for index, evaluation in completed_instances:
            results[index]["evaluation"] = evaluation
            _atomic_json_dump(evaluated_path, results)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(run_index, index) for index in pending]
            for future in concurrent.futures.as_completed(futures):
                index, evaluation = future.result()
                results[index]["evaluation"] = evaluation
                _atomic_json_dump(evaluated_path, results)

    merge_summaries: dict[str, Any] = {}
    file_coverage: dict[str, Any] = {}
    if not args.no_merge:
        for kind in ("all_executed", "passing"):
            status = merge_coverage(
                image=args.image,
                output_dir=output_dir,
                results=results,
                kind=kind,
                jacoco_version=args.jacoco_version,
                timeout=args.merge_timeout,
            )
            merge_summaries[kind] = status
            file_coverage[kind] = collect_merged_file_coverage(
                output_dir, results, kind, status["modules"]
            )

    evaluated = [item.get("evaluation") or {} for item in results if item.get("evaluation")]
    syntax_results = [item["syntax_evaluation"] for item in results]
    syntax_correct = sum(entry.get("correct") is True for entry in syntax_results)
    syntax_parser_available = _get_tree_sitter_parser is not None
    summary = {
        "input": str(data_file),
        "image": args.image,
        "source_target_count": source_target_count,
        "skipped_generation_count": skipped_generation_count,
        "target_count": len(source_items),
        "evaluated_count": len(evaluated),
        "compile_pass_count": sum(entry.get("compile_pass") is True for entry in evaluated),
        "test_pass_count": sum(entry.get("test_pass") is True for entry in evaluated),
        "exec_count": sum(bool(entry.get("jacoco_exec")) for entry in evaluated),
        "syntax": {
            "parser": "tree-sitter-java",
            "parser_available": syntax_parser_available,
            "total": len(syntax_results),
            "correct": syntax_correct,
            "incorrect": len(syntax_results) - syntax_correct,
            "correct_rate": syntax_correct / len(syntax_results) if syntax_results else 0.0,
        },
        "merge": merge_summaries,
    }
    _atomic_json_dump(evaluated_path, results)
    _atomic_json_dump(output_dir / "file_coverage.json", file_coverage)
    _atomic_json_dump(output_dir / "summary.json", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate each generated Java test in a fresh container and merge JaCoCo exec data."
    )
    parser.add_argument("--data-file", type=Path, required=True, help="Generated-test JSON")
    parser.add_argument("--image", help="Prebuilt project image")
    parser.add_argument("--dockerfile", type=Path, help="Build an image from this Dockerfile first")
    parser.add_argument("--build-context", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--jacoco-version", default=DEFAULT_JACOCO_VERSION)
    parser.add_argument("--timeout", type=int, default=1200, help="Seconds per function")
    parser.add_argument("--merge-timeout", type=int, default=1800)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--only-successfully-generated",
        action="store_true",
        help="Evaluate only items whose mini-swe-agent exit status is Submitted",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--redo-existing",
        action="store_true",
        help="With --resume, force reevaluation of entries selected by --start/--limit",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of independently isolated function containers to evaluate concurrently",
    )
    parser.add_argument("--no-merge", action="store_true")
    parser.add_argument("--keep-logs", action="store_true")
    parser.add_argument("--keep-individual-xml", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.image and not args.dockerfile:
        parser.error("one of --image or --dockerfile is required")
    if args.start < 0 or (args.limit is not None and args.limit < 1) or args.workers < 1:
        parser.error("--start must be non-negative; --limit and --workers must be positive")
    if not args.image:
        args.image = f"adverbug-java-eval-{_safe_name(args.data_file.stem)}:latest"
    if args.dockerfile:
        _build_image(args.dockerfile.resolve(), args.build_context.resolve(), args.image)
    summary = evaluate_dataset(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
