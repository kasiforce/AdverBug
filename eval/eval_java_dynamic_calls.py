#!/usr/bin/env python3
"""Prototype dynamic direct-call coverage for Java function-level targets.

This is intentionally separate from ``eval_java.py``.  It reuses the existing
isolated Java evaluation container, adds a small Java agent through Maven's
agent argument, and records runtime caller-to-callee edges.  JaCoCo's
method counters are then attached to the directly called production methods.

The result is deliberately limited to direct calls observed at runtime.  Calls
through reflection or code paths not exercised by the generated tests are not
reported as observed edges.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

from eval_java import _copy_if_present, _safe_name, _stage_item


EVAL_DIR = Path(__file__).resolve().parent
INSTANCE_SCRIPT = EVAL_DIR / "java_eval_container.sh"
DEFAULT_JACOCO_VERSION = "0.8.14"
ASM_JAR = EVAL_DIR / "vendor" / "asm-9.8.jar"


AGENT_SOURCE = r'''
import java.io.BufferedWriter;
import java.io.FileWriter;
import java.io.IOException;
import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.IllegalClassFormatException;
import java.lang.instrument.Instrumentation;
import java.security.ProtectionDomain;
import java.util.HashMap;
import java.util.Map;

import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

public final class TraceAgent {
    public static void premain(String arguments, Instrumentation instrumentation) {
        Map<String, String> options = parse(arguments);
        String output = options.get("output");
        String prefix = options.get("prefix");
        String targetClass = options.get("targetClass");
        String targetMethod = options.get("targetMethod");
        if (output == null || prefix == null || prefix.length() == 0) {
            return;
        }
        Trace.initialize(output);
        instrumentation.addTransformer(new Transformer(prefix, targetClass, targetMethod));
    }

    private static Map<String, String> parse(String arguments) {
        Map<String, String> result = new HashMap<String, String>();
        if (arguments == null) {
            return result;
        }
        for (String part : arguments.split(",")) {
            int separator = part.indexOf('=');
            if (separator > 0) {
                result.put(part.substring(0, separator), part.substring(separator + 1));
            }
        }
        return result;
    }

    private static final class Transformer implements ClassFileTransformer {
        private final String prefix;
        Transformer(String prefix, String targetClass, String targetMethod) {
            this.prefix = prefix;
        }

        @Override
        public byte[] transform(
                ClassLoader loader,
                String className,
                Class<?> classBeingRedefined,
                ProtectionDomain protectionDomain,
                byte[] classfileBuffer) throws IllegalClassFormatException {
            if (className == null || !className.startsWith(prefix)
                    || className.startsWith("jdk/")
                    || className.startsWith("java/")) {
                return null;
            }
            try {
                ClassReader reader = new ClassReader(classfileBuffer);
                ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS);
                ClassVisitor visitor = new ClassVisitor(Opcodes.ASM9, writer) {
                    @Override
                    public MethodVisitor visitMethod(
                            int access, String name, String descriptor,
                            String signature, String[] exceptions) {
                        MethodVisitor delegate = super.visitMethod(
                                access, name, descriptor, signature, exceptions);
                        // Injecting before invokespecial in a constructor can
                        // violate the JVM's uninitialized-this rules.
                        if ("<init>".equals(name) || "<clinit>".equals(name)
                                || (access & (Opcodes.ACC_ABSTRACT | Opcodes.ACC_NATIVE)) != 0) {
                            return delegate;
                        }
                        return new MethodVisitor(Opcodes.ASM9, delegate) {
                            @Override
                            public void visitMethodInsn(
                                    int opcode, String owner, String calledName,
                                    String calledDescriptor, boolean isInterface) {
                                if (owner.startsWith(prefix)
                                        && !"<init>".equals(calledName)
                                        && !"<clinit>".equals(calledName)
                                        && !"$jacocoInit".equals(calledName)
                                        && !calledName.startsWith("access$")) {
                                    Trace.recordStatic(
                                            className, name, owner, calledName, calledDescriptor);
                                }
                                super.visitMethodInsn(
                                        opcode, owner, calledName, calledDescriptor, isInterface);
                            }

                            @Override
                            public void visitCode() {
                                super.visitCode();
                                visitLdcInsn(className);
                                visitLdcInsn(name);
                                visitLdcInsn(descriptor);
                                visitMethodInsn(
                                        Opcodes.INVOKESTATIC,
                                        "TraceAgent$Trace",
                                        "record",
                                        "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)V",
                                        false);
                            }
                        };
                    }
                };
                reader.accept(visitor, 0);
                return writer.toByteArray();
            } catch (Throwable ignored) {
                // A tracing failure must never make the generated test fail.
                return null;
            }
        }
    }

    public static final class Trace {
        private static BufferedWriter writer;

        static synchronized void initialize(String output) {
            try {
                writer = new BufferedWriter(new FileWriter(output, true));
            } catch (IOException ignored) {
                writer = null;
            }
        }

        public static synchronized void record(
                String calleeClass, String calleeMethod, String descriptor) {
            if (writer == null) {
                return;
            }
            StackTraceElement[] stack = Thread.currentThread().getStackTrace();
            String callerClass = null;
            String callerMethod = null;
            boolean foundCallee = false;
            for (StackTraceElement frame : stack) {
                if (frame.getClassName().equals("TraceAgent$Trace")
                        || frame.getClassName().equals("java.lang.Thread")) {
                    continue;
                }
                if (!foundCallee) {
                    foundCallee = true;
                    continue;
                }
                callerClass = frame.getClassName().replace('.', '/');
                callerMethod = frame.getMethodName();
                break;
            }
            if (callerClass == null || callerMethod == null) {
                return;
            }
            try {
                writer.write(callerClass);
                writer.write('\t');
                writer.write(callerMethod);
                writer.write('\t');
                writer.write(calleeClass);
                writer.write('\t');
                writer.write(calleeMethod);
                writer.write('\t');
                writer.write(descriptor);
                writer.newLine();
                writer.flush();
            } catch (IOException ignored) {
                // Tracing remains best effort.
            }
        }

        public static synchronized void recordStatic(
                String callerClass, String callerMethod,
                String calleeClass, String calleeMethod, String descriptor) {
            if (writer == null) {
                return;
            }
            try {
                writer.write("S\t");
                writer.write(callerClass);
                writer.write('\t');
                writer.write(callerMethod);
                writer.write('\t');
                writer.write(calleeClass);
                writer.write('\t');
                writer.write(calleeMethod);
                writer.write('\t');
                writer.write(descriptor);
                writer.newLine();
                writer.flush();
            } catch (IOException ignored) {
                // Tracing remains best effort.
            }
        }
    }
}
'''


def _build_agent(output_dir: Path) -> Path:
    source_dir = output_dir / "agent-src"
    classes_dir = output_dir / "agent-classes"
    source_dir.mkdir(parents=True, exist_ok=True)
    classes_dir.mkdir(parents=True, exist_ok=True)
    source = source_dir / "TraceAgent.java"
    source.write_text(textwrap.dedent(AGENT_SOURCE), encoding="utf-8")
    if not ASM_JAR.is_file():
        raise FileNotFoundError(f"Java ASM dependency is missing: {ASM_JAR}")
    subprocess.run(
        [
            "javac",
            "-cp", str(ASM_JAR),
            "--release", "8",
            "-d",
            str(classes_dir),
            str(source),
        ],
        check=True,
    )
    subprocess.run(["jar", "xf", str(ASM_JAR)], cwd=classes_dir, check=True)
    manifest = output_dir / "agent-manifest.txt"
    manifest.write_text("Premain-Class: TraceAgent\nCan-Redefine-Classes: false\n\n", encoding="utf-8")
    jar = output_dir / "trace-agent.jar"
    subprocess.run(["jar", "cfm", str(jar), str(manifest), "-C", str(classes_dir), "."], check=True)
    wrapper = output_dir / "mvn-wrapper"
    wrapper.write_text(
        """#!/usr/bin/env bash
set -e
args=()
for arg in \"$@\"; do
    case \"$arg\" in
        -D*argLine=*) args+=(\"$arg ${TRACE_AGENT_ARGUMENT:-}\") ;;
        *) args+=(\"$arg\") ;;
    esac
done
if [[ -x /usr/bin/mvn ]]; then
    exec /usr/bin/mvn \"${args[@]}\"
fi
exec /usr/share/maven/bin/mvn \"${args[@]}\"
""",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return jar


def _prefix_for(item: dict[str, Any]) -> str:
    full_class = str(item.get("full_class_name") or "").replace(".", "/")
    if not full_class:
        raise ValueError("function target is missing full_class_name")
    parts = full_class.split("/")
    # The first three components usually identify the project namespace (for
    # example org/thymeleaf or org/apache/parquet).  The option can override
    # this when a repository uses a different package layout.
    return "/".join(parts[: min(3, max(1, len(parts) - 1))])


def _instance_id(index: int, item: dict[str, Any]) -> str:
    identity = "|".join(str(item.get(key, "")) for key in ("src_file", "class_name", "name", "start_line"))
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:10]
    return f"{index:04d}_{_safe_name(str(item.get('name', 'function')), 35)}_{digest}"


def _counter(element: ET.Element, kind: str) -> dict[str, int | float]:
    counter = element.find(f"./counter[@type='{kind}']")
    if counter is None:
        return {"total": 0, "covered": 0, "missed": 0, "rate": 0.0}
    missed = int(counter.attrib.get("missed", 0))
    covered = int(counter.attrib.get("covered", 0))
    total = missed + covered
    return {"total": total, "covered": covered, "missed": missed, "rate": covered / total if total else 0.0}


def _method_coverage(xml_path: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    if not xml_path.is_file():
        return {}
    root = ET.parse(xml_path).getroot()
    methods: dict[tuple[str, str, str], dict[str, Any]] = {}
    for package in root.findall("package"):
        package_name = package.attrib.get("name", "")
        for cls in package.findall("class"):
            class_name = cls.attrib.get("name", "")
            if not class_name:
                continue
            for method in cls.findall("method"):
                name = method.attrib.get("name", "")
                descriptor = method.attrib.get("desc", "")
                if name:
                    methods[(class_name, name, descriptor)] = {
                        "class": class_name.replace("/", "."),
                        "method": name,
                        "descriptor": descriptor,
                        "line": _counter(method, "LINE"),
                        "branch": _counter(method, "BRANCH"),
                    }
    return methods


def _dynamic_edges(path: Path, item: dict[str, Any]) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    target_class = str(item.get("full_class_name") or "").replace(".", "/")
    target_method = str(item.get("name") or "")
    counts: Counter[tuple[str, str, str, str, str]] = Counter()
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = raw.split("\t")
        if len(parts) != 5:
            continue
        caller_class, caller_method, callee_class, callee_method, descriptor = parts
        if (caller_class == target_class and caller_method == target_method
                and callee_method != "$jacocoInit"
                and not callee_method.startswith("access$")):
            counts[(caller_class, caller_method, callee_class, callee_method, descriptor)] += 1
    return [
        {
            "caller_class": caller_class.replace("/", "."),
            "caller_method": caller_method,
            "callee_class": callee_class.replace("/", "."),
            "callee_method": callee_method,
            "descriptor": descriptor,
            "call_count": count,
        }
        for (caller_class, caller_method, callee_class, callee_method, descriptor), count in sorted(counts.items())
    ]


def _static_edges(path: Path, item: dict[str, Any]) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    edges: set[tuple[str, str, str]] = set()
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = raw.split("\t")
        if len(parts) != 6 or parts[0] != "S":
            continue
        _, caller_class, caller_method, callee_class, callee_method, descriptor = parts
        target_class = str(item.get("full_class_name") or "").replace(".", "/")
        if caller_class != target_class or caller_method != str(item.get("name") or ""):
            continue
        edges.add((callee_class, callee_method, descriptor))
    return [
        {
            "callee_class": callee_class.replace("/", "."),
            "callee_method": callee_method,
            "descriptor": descriptor,
        }
        for callee_class, callee_method, descriptor in sorted(edges)
    ]


def _method_key(entry: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(entry["callee_class"]).replace(".", "/"),
        str(entry["callee_method"]),
        str(entry["descriptor"]),
    )


def _aggregate_candidate_coverage(
    methods: dict[tuple[str, str, str], dict[str, Any]],
    candidate_keys: set[tuple[str, str, str]],
) -> dict[str, Any]:
    """Aggregate JaCoCo counters for the statically or dynamically called methods.

    Keep the denominator aligned with the Python dynamic-call evaluator: the
    candidate set is S union D.  A candidate absent from the JaCoCo report is
    reported through the match counts, but is not silently treated as a method
    with zero executable lines or branches.
    """
    result: dict[str, Any] = {
        "line": {"covered": 0, "total": 0, "rate": None},
        "branch": {"covered": 0, "total": 0, "rate": None},
        "matched_function_count": 0,
        "unmatched_function_count": 0,
    }
    for key in candidate_keys:
        coverage = methods.get(key)
        if coverage is None:
            result["unmatched_function_count"] += 1
            continue
        result["matched_function_count"] += 1
        for kind in ("line", "branch"):
            counter = coverage.get(kind) or {}
            result[kind]["covered"] += int(counter.get("covered", 0) or 0)
            result[kind]["total"] += int(counter.get("total", 0) or 0)
    for kind in ("line", "branch"):
        total = result[kind]["total"]
        result[kind]["rate"] = result[kind]["covered"] / total if total else None
    return result


def _evaluate_one(
    *, item: dict[str, Any], index: int, image: str, output_dir: Path,
    agent_jar: Path, timeout: int, trace_prefix: str | None,
) -> dict[str, Any]:
    instance_id = _instance_id(index, item)
    run_dir = output_dir / "runs" / instance_id
    run_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dynamic-java-input-") as stage_name:
        stage_dir = Path(stage_name)
        _stage_item(item, stage_dir)
        prefix = trace_prefix or _prefix_for(item)
        container_name = f"adverbug-dynamic-{_safe_name(instance_id, 70)}"
        command = [
            "docker", "run", "--rm", "--name", container_name,
            "-v", f"{stage_dir}:/eval-input:ro",
            "-v", f"{run_dir}:/results",
            "-v", f"{INSTANCE_SCRIPT}:/eval/java_eval_container.sh:ro",
            "-v", f"{agent_jar}:/trace/trace-agent.jar:ro",
            "-v", f"{agent_jar.with_name('mvn-wrapper')}:/trace-bin/mvn:ro",
            "-e", "PATH=/trace-bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "-e", "TRACE_AGENT_ARGUMENT=-javaagent:/trace/trace-agent.jar=output=/results/calls.tsv,prefix=" + prefix
                + ",targetClass=" + str(item.get("full_class_name") or "").replace(".", "/")
                + ",targetMethod=" + str(item.get("name") or ""),
            "-e", "JACOCO_VERSION=" + DEFAULT_JACOCO_VERSION,
            image, "bash", "/eval/java_eval_container.sh",
        ]
        started = time.monotonic()
        try:
            completed = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
            run_status = {"container_exit_code": completed.returncode}
            (run_dir / "docker.stdout.log").write_text(completed.stdout, encoding="utf-8")
            (run_dir / "docker.stderr.log").write_text(completed.stderr, encoding="utf-8")
        except subprocess.TimeoutExpired as error:
            subprocess.run(["docker", "rm", "-f", container_name], check=False, capture_output=True)
            run_status = {"container_exit_code": None, "timeout": True, "error": str(error)}

    compile_code = (run_dir / "compile_exit_code.txt").read_text().strip() if (run_dir / "compile_exit_code.txt").is_file() else None
    test_code = (run_dir / "test_exit_code.txt").read_text().strip() if (run_dir / "test_exit_code.txt").is_file() else None
    xml_path = run_dir / "jacoco.xml"
    methods = _method_coverage(xml_path)
    edges = _dynamic_edges(run_dir / "calls.tsv", item)
    for edge in edges:
        key = (
            edge["callee_class"].replace(".", "/"),
            edge["callee_method"],
            edge["descriptor"],
        )
        edge["coverage"] = methods.get(key)
        if edge["coverage"] is None:
            edge["coverage_status"] = "not_present_in_jacoco_report"
    static_edges = _static_edges(run_dir / "calls.tsv", item)
    for edge in static_edges:
        edge["coverage"] = methods.get(_method_key(edge))
        if edge["coverage"] is None:
            edge["coverage_status"] = "not_present_in_jacoco_report"
    static_keys = {_method_key(edge) for edge in static_edges}
    dynamic_keys = {_method_key(edge) for edge in edges}
    candidate_keys = static_keys | dynamic_keys
    candidate_coverage = _aggregate_candidate_coverage(methods, candidate_keys)
    called_function_coverage = {
        "candidate_scope": "instrumented_project_methods",
        "static_called_function_count": len(static_keys),
        "executed_called_function_count": len(dynamic_keys),
        "candidate_called_function_count": len(candidate_keys),
        "covered_candidate_count": len(dynamic_keys),
        "coverage_rate": len(dynamic_keys) / len(candidate_keys) if candidate_keys else None,
        "coverage_status": "measured" if candidate_keys else "no_called_functions",
        "static_and_dynamic_count": len(static_keys & dynamic_keys),
        "static_only_count": len(static_keys - dynamic_keys),
        "dynamic_only_count": len(dynamic_keys - static_keys),
        "line": candidate_coverage["line"],
        "branch": candidate_coverage["branch"],
        "matched_function_count": candidate_coverage["matched_function_count"],
        "unmatched_function_count": candidate_coverage["unmatched_function_count"],
    }
    result = {
        "instance_id": instance_id,
        "src_file": item.get("src_file"),
        "class_name": item.get("full_class_name") or item.get("class_name"),
        "target_function": item.get("name"),
        "target_start_line": item.get("start_line"),
        "compile_pass": compile_code == "0",
        "test_pass": test_code == "0",
        "compile_exit_code": compile_code,
        "test_exit_code": test_code,
        "duration_seconds": time.monotonic() - started,
        "trace_prefix": prefix,
        "static_called_functions": static_edges,
        "direct_called_functions": edges,
        "called_function_coverage": called_function_coverage,
        "trace_record_count": sum(edge["call_count"] for edge in edges),
        "jacoco_report_found": xml_path.is_file(),
        **run_status,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-file", type=Path, required=True, help="Function-level generated-test JSON")
    parser.add_argument("--image", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--trace-prefix", help="Override the internal JVM class prefix to instrument")
    args = parser.parse_args()

    args.data_file = args.data_file.resolve()
    args.output_dir = args.output_dir.resolve()
    items = json.loads(args.data_file.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise SystemExit("data file must contain a JSON list")
    selected = items[args.start : args.start + args.limit if args.limit is not None else None]
    selected = [item for item in selected if str(item.get("target_type") or "").lower() != "source_file"]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dynamic-agent-") as agent_dir:
        agent_jar = _build_agent(Path(agent_dir))
        results = []
        for index, item in enumerate(selected, start=args.start):
            results.append(_evaluate_one(
                item=item, index=index, image=args.image, output_dir=args.output_dir,
                agent_jar=agent_jar, timeout=args.timeout, trace_prefix=args.trace_prefix,
            ))
            print(f"[{len(results)}/{len(selected)}] {item.get('full_class_name')}.{item.get('name')}", flush=True)
    output = args.output_dir / "dynamic_call_results.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"target_count": len(results), "output": str(output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
