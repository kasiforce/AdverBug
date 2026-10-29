"""
adver_dual.py —— 双大模型过滤的错误代码生成流程。

与 adver.py（旧流程）的区别（详见分析报告）：
1. 删除"原测试套件"过滤闸门，改由两个不同厂商的大模型按评测协议生成测试并过滤；
   原测试套件降级为元数据：验收时跑一次，记录 escaped_original_suite / 失败用例，
   被其检出即作为"非等效"的强证据。
2. 过滤协议与评测管线同源：复用 gen_test/llm_gentests.py 的 TestCodeGenerator
   （specification 模式模板、temperature=0、max_K=3 重试），输入为"错误代码 + 规范"，
   与被评测模型看到的信息一致——过滤准则即"在评测协议下该模型未检出此 bug"。
3. 只在错误代码上运行过滤测试，按 surefire 失败类型分流（不跑原代码做差分）：
   - 断言失败（failure）= 过滤模型检出 bug → 反馈给 bug 生成器重试；
   - 执行异常（error）→ 迭代修复测试套件，bug 保留；
   - 编译始终失败 / 空套件 = 套件问题 → 重新生成套件，不判检出。
4. 等效判定沿用 valid_agent.py 的语义行为一致性判定。

用法（容器内，WORKDIR=/testbed 为项目根目录）：
    python3 /testbed/adver_dual.py --data-path /testbed/<data>.json \
        --filter-model-a deepseek-v3.2 --filter-model-b qwen3-coder-480b-a35b-instruct

通过环境变量 GPT_API_KEY / QWEN_API_KEY 配置两家服务的凭证；endpoint
分别默认使用 Agicto 和 Qianwen，也可通过 GPT_API_ENDPOINT /
QWEN_API_ENDPOINT 覆盖。

输出：
    /testbed/final_results.json   仅收录被接受的条目（ schema 与旧流程兼容，额外字段见下）
    /testbed/filter_stats.json    全部条目的尝试轨迹（用于新旧流程 A/B 对比），
                                  额外记录每次尝试的 bug_code，以及每个过滤模型
                                  最终生成的测试套件 generated_tests。
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from llm_config import LLMConfig
from bug_generation_agent import BugGenerationAgent
from valid_agent import ValidAgent
from usage_tracker import usage_tracker
from filter_test_gen import FilterTestGenerationAgent

TESTBED = "/testbed"
# In a reactor build the selected test class normally belongs to only one
# module.  Without this flag, every other module makes `mvn test -Dtest=...`
# fail with "No tests matching pattern ...", even when the selected module's
# tests ran successfully.
MVN_SKIP_ARGS = [
    "-Drat.skip=true",
    "-Dformatter.skip=true",
    "-DforkCount=0",
    "-DskipTests=false",
    "-Dsurefire.failIfNoSpecifiedTests=false",
    "-Dcheckstyle.skip=true",
    "-Dspotless.check.skip=true"
]

DEFAULT_GPT_ENDPOINT = "https://api.agicto.cn/v1"
DEFAULT_QWEN_ENDPOINT = "https://maas.qianwenaiapi.com/compatible-mode/v1"
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1"


def uses_gpt_provider(model_name):
    """Route GPT model IDs to the GPT credential and endpoint."""
    normalized = str(model_name or "").strip().lower()
    return normalized.startswith("gpt-") or normalized.startswith("openai/gpt-")

# filter_stats.json 中 bug_code / generated_tests 的单字段最大字符数。
# 设为 None 表示不截断（文件会很大）。
TRUNCATE_LIMIT = None

# Cached index of production-only Java declarations/imports used for
# deterministic test-compilation repairs. Test sources are intentionally never
# indexed or supplied to a model.
_PRODUCTION_JAVA_INDEX = None
MAX_AUTO_COMPILE_REPAIRS = 3


def _truncate(text, limit=TRUNCATE_LIMIT):
    """截断过长字符串，避免 filter_stats.json 体积失控。limit=None 时不截断。"""
    if text is None or limit is None:
        return text
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, total {len(text)} chars]"


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def sh(cmd, timeout=1800, cwd=None):
    try:
        return subprocess.run(cmd, cwd=cwd or TESTBED, capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired as e:
        out = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode("utf-8", "ignore")
        err = e.stderr if isinstance(e.stderr, str) else (e.stderr or b"").decode("utf-8", "ignore")
        return subprocess.CompletedProcess(cmd, returncode=-1, stdout=out, stderr=err)


# def mvn(goal_args, timeout=1800):
#     return sh(["mvn"] + goal_args + MVN_SKIP_ARGS, timeout=timeout)
def _maven_cmd():
    """优先用项目 wrapper，其次用全局 mvn。"""
    wrapper = os.path.join(TESTBED, "mvnw")
    if os.path.isfile(wrapper) and os.access(wrapper, os.X_OK):
        # Use an absolute path because module-scoped builds run with the module
        # directory as their working directory rather than the repository root.
        return [wrapper]
    return ["mvn"]


def maven_module_dir(source_path=None):
    """Return the nearest Maven module containing ``source_path``.

    Dataset paths can point to files that do not exist yet (notably generated
    tests), so resolution must not require the final path to exist.  If the path
    is outside the repository or no enclosing ``pom.xml`` is found, retain the
    previous repository-root behavior.
    """
    root = Path(TESTBED).resolve()
    if not source_path:
        return str(root)

    path = Path(source_path)
    if not path.is_absolute():
        path = root / path
    path = path.resolve(strict=False)
    start = path if path.is_dir() else path.parent
    if start != root and root not in start.parents:
        return str(root)

    for directory in (start, *start.parents):
        if (directory / "pom.xml").is_file():
            return str(directory)
        if directory == root:
            break
    return str(root)


def mvn(goal_args, timeout=1800, source_path=None):
    module_dir = maven_module_dir(source_path)
    return sh(_maven_cmd() + goal_args + MVN_SKIP_ARGS,
              timeout=timeout, cwd=module_dir)


def run_compiled_test(test_class, test_file=None, timeout=1800):
    """Run an already test-compiled class without re-entering Maven's lifecycle.

    ``mvn test`` implicitly executes ``test-compile``.  The caller has just
    completed that gate successfully, so invoking Surefire's goal directly
    reuses ``target/classes`` and ``target/test-classes`` while preserving the
    project's configured Surefire provider, JVM options, and reports.
    """
    return mvn(["surefire:test", f"-Dtest={test_class}"], timeout=timeout,
               source_path=test_file)


def maven_compile_diagnostics(output, fallback_limit=6000):
    """Return Maven's actionable compilation diagnostics, not its full log.

    Reactor summaries, module timings, warnings and Maven help text commonly
    make a repair prompt tens of thousands of characters long while conveying
    no information about how to fix a Java source error.  Keep the compiler's
    ``[ERROR]`` records from the compilation-error section, including its
    indented ``symbol`` and ``location`` continuations.  If a plugin uses an
    unfamiliar format, retain a bounded tail instead of returning no feedback.
    """
    if not output:
        return ""
    lines = output.splitlines()
    start = next((i for i, line in enumerate(lines)
                  if "COMPILATION ERROR" in line), None)
    if start is not None:
        end = next((i for i in range(start + 1, len(lines))
                    if "Reactor Summary" in lines[i]
                    or "-> [Help" in lines[i]), len(lines))
        diagnostics = []
        for line in lines[start + 1:end]:
            stripped = line.strip()
            if not stripped or set(stripped) <= {"[", "]", "-", " ", "I", "N", "F", "O", "E", "R", "W", "A", "G"}:
                continue
            if line.lstrip().startswith("[ERROR]"):
                diagnostics.append(line)
        if diagnostics:
            return "\n".join(diagnostics)

    # Some Maven/compiler plugins omit the standard section header.  Preserve
    # only explicit error lines when possible, otherwise retain a short tail.
    error_lines = [line for line in lines if "[ERROR]" in line or "error:" in line.lower()]
    if error_lines:
        return "\n".join(error_lines[-100:])
    return output[-fallback_limit:]


def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path, content):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def set_src_code(src_file, new_code, old_code):
    """把 src_file 中的 old_code 片段替换为 new_code。返回是否替换成功。"""
    src = read_text(src_file)
    occurrences = src.count(old_code)
    if occurrences != 1:
        print(f"拒绝替换 {src_file}: 目标代码出现 {occurrences} 次（预期 1 次）")
        return False
    write_text(src_file, src.replace(old_code, new_code, 1))
    return True


def snapshot_production_sources():
    """Capture production Java files before a Bash-capable test agent runs."""
    pattern = os.path.join(TESTBED, "**", "src", "main", "java", "**", "*.java")
    return {path: read_text(path) for path in glob.glob(pattern, recursive=True)}


def restore_production_sources(snapshot):
    """Undo every production-source edit a test agent may have made."""
    pattern = os.path.join(TESTBED, "**", "src", "main", "java", "**", "*.java")
    for path in glob.glob(pattern, recursive=True):
        if path not in snapshot:
            os.remove(path)
    for path, content in snapshot.items():
        write_text(path, content)


def _production_java_index():
    """Index types and imports under ``src/main/java`` only.

    The index is deliberately shallow: it supports only unambiguous import and
    case-only method-name repairs. Ambiguous API/semantic errors stay with the
    LLM repair path rather than risking a behavioral change in a generated
    test.
    """
    global _PRODUCTION_JAVA_INDEX
    if _PRODUCTION_JAVA_INDEX is not None:
        return _PRODUCTION_JAVA_INDEX

    type_index = {}
    import_index = {}
    pattern = os.path.join(TESTBED, "**", "src", "main", "java", "**", "*.java")
    for path in glob.glob(pattern, recursive=True):
        try:
            content = read_text(path)
        except OSError:
            continue
        package_match = re.search(r"^\s*package\s+([\w.]+)\s*;", content, re.MULTILINE)
        package_name = package_match.group(1) if package_match else ""
        for imported in re.findall(r"^\s*import\s+(?!static\s+)([\w.]+)\s*;", content, re.MULTILINE):
            simple_name = imported.rsplit(".", 1)[-1]
            import_index.setdefault(simple_name, set()).add(imported)

        # Track lexical type nesting well enough to qualify public nested
        # types. This is not a full Java parser, but it is conservative because
        # only a unique candidate is ever applied.
        nesting = []
        brace_depth = 0
        for line_number, line in enumerate(content.splitlines(), start=1):
            while nesting and brace_depth < nesting[-1][1]:
                nesting.pop()
            match = re.search(
                r"\b(?:class|interface|enum|record)\s+([A-Za-z_$][\w$]*)\b", line)
            opens = line.count("{")
            closes = line.count("}")
            if match:
                simple_name = match.group(1)
                parents = [name for name, _depth in nesting]
                qualified_name = ".".join(
                    part for part in ([package_name] + parents + [simple_name]) if part)
                candidate = {
                    "qualified_name": qualified_name,
                    "path": path,
                    "line": line_number,
                    "public": bool(re.search(r"\bpublic\b", line)),
                }
                type_index.setdefault(simple_name, []).append(candidate)
                nesting.append((simple_name, brace_depth + max(opens - closes, 1)))
            brace_depth += opens - closes
            while nesting and brace_depth < nesting[-1][1]:
                nesting.pop()

    _PRODUCTION_JAVA_INDEX = {"types": type_index, "imports": import_index}
    return _PRODUCTION_JAVA_INDEX


def _unique_values(values):
    values = sorted(set(values))
    return values[0] if len(values) == 1 else None


def _test_package(tests):
    match = re.search(r"^\s*package\s+([\w.]+)\s*;", tests, re.MULTILINE)
    return match.group(1) if match else ""


def _insert_imports(tests, imports):
    """Insert explicit imports after the existing header without altering code."""
    if not imports:
        return tests
    existing = set(re.findall(r"^\s*import\s+(?:static\s+)?([\w.]+)\s*;", tests, re.MULTILINE))
    additions = [item for item in imports if item.rsplit(" ", 1)[-1][:-1] not in existing]
    if not additions:
        return tests
    lines = tests.splitlines()
    insert_at = 0
    for index, line in enumerate(lines):
        if re.match(r"^\s*(?:package|import)\b", line):
            insert_at = index + 1
    lines[insert_at:insert_at] = additions
    return "\n".join(lines) + ("\n" if tests.endswith("\n") else "")


def _case_only_method_replacements(tests, compiler_error):
    """Correct a method spelling only when production declarations agree."""
    requested = re.findall(r"symbol:\s+method\s+([A-Za-z_$][\w$]*)\s*\(", compiler_error)
    if not requested:
        return tests, []
    candidates = {}
    pattern = os.path.join(TESTBED, "**", "src", "main", "java", "**", "*.java")
    for path in glob.glob(pattern, recursive=True):
        try:
            content = read_text(path)
        except OSError:
            continue
        # Declaration-oriented pattern deliberately avoids matching call sites.
        for match in re.finditer(
            r"(?:public|protected|private|static|final|synchronized|native|abstract|\s)+"
            r"[A-Za-z_$][\w$<>, ?\[\].]*\s+([A-Za-z_$][\w$]*)\s*\(", content):
            name = match.group(1)
            candidates.setdefault(name.lower(), set()).add(name)

    repairs = []
    for wrong_name in requested:
        correct_name = _unique_values(candidates.get(wrong_name.lower(), set()))
        if not correct_name or correct_name == wrong_name:
            continue
        tests, count = re.subn(rf"\b{re.escape(wrong_name)}\s*\(",
                               f"{correct_name}(", tests)
        if count:
            repairs.append({"kind": "method_case", "from": wrong_name, "to": correct_name})
    return tests, repairs


def deterministic_test_compile_repair(tests, compiler_error):
    """Apply safe, source-backed repairs without asking an LLM.

    Only explicit imports for a unique production type/import and case-only
    method spellings are touched. Assertions, input data, expected values, and
    general API selection are never changed here.
    """
    index = _production_java_index()
    package_name = _test_package(tests)
    imports = []
    repairs = []
    missing_types = re.findall(r"symbol:\s+class\s+([A-Za-z_$][\w$]*)", compiler_error)
    for simple_name in sorted(set(missing_types)):
        # Never auto-import a non-public declaration. If a same-package
        # package-private type were usable, Java would already resolve its bare
        # name; an unresolved type needs an externally accessible declaration.
        type_candidates = [candidate for candidate in index["types"].get(simple_name, [])
                           if candidate.get("public")]
        qualified = _unique_values(candidate["qualified_name"] for candidate in type_candidates)
        if qualified is None:
            qualified = _unique_values(index["imports"].get(simple_name, set()))
        if not qualified:
            continue
        qualified_package = qualified.rsplit(".", 1)[0] if "." in qualified else ""
        if qualified_package != package_name:
            imports.append(f"import {qualified};")
            repairs.append({"kind": "missing_import", "symbol": simple_name,
                            "import": qualified})

    repaired = _insert_imports(tests, imports)
    repaired, method_repairs = _case_only_method_replacements(repaired, compiler_error)
    repairs.extend(method_repairs)
    return repaired, repairs


def test_class_name(test_file):
    return os.path.splitext(os.path.basename(test_file))[0]


def delete_test_files_in_test_dirs(project_root):
    """Remove existing Java test inputs and stale compiled test artifacts.

    Maven modules below a top-level ``tests/`` directory still need their
    ``pom.xml`` files, so deleting every such directory would destroy the
    reactor.  Remove conventional source-set contents instead, plus compiled
    test outputs left in the prebuilt image.  The generated target test is
    written only after this one-time isolation step.
    """
    root = Path(project_root)
    source_set_names = {"test", "tests", "androidtest", "testfixtures"}
    test_source_suffixes = {".java", ".scala", ".kt", ".groovy"}
    skipped_names = {".git", "venv", ".venv", "__pycache__", "node_modules"}
    artifact_names = {
        "test-classes", "generated-test-sources", "surefire-reports",
        "failsafe-reports", "test-results",
    }
    source_roots = []
    artifact_roots = []

    for current, dirs, _files in os.walk(root, topdown=True):
        dirs[:] = [name for name in dirs if name not in skipped_names]
        current_path = Path(current)
        lowered = current_path.name.lower()
        parent_lowered = current_path.parent.name.lower()
        if parent_lowered == "src" and lowered in source_set_names:
            source_roots.append(current_path)
            continue
        if lowered in artifact_names and (
                current_path.parent.name == "target" or "build" in current_path.parts):
            artifact_roots.append(current_path)
            dirs[:] = []

    removed_files = 0
    for directory in source_roots:
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix.lower() in test_source_suffixes:
                try:
                    path.unlink()
                    removed_files += 1
                except OSError as error:
                    print(f"删除失败 {path}: {error}")

    for directory in artifact_roots:
        try:
            removed_files += sum(1 for path in directory.rglob("*") if path.is_file())
            shutil.rmtree(directory)
        except OSError as error:
            print(f"删除失败 {directory}: {error}")

    print(
        f"测试隔离完成：扫描 {len(source_roots)} 个测试源码目录（保留 resources）、"
        f"{len(artifact_roots)} 个测试构建产物目录，共 {removed_files} 个文件")


# ---------------------------------------------------------------------------
# Surefire 结果解析（per-test 差分仲裁）
# ---------------------------------------------------------------------------

def surefire_xml_files():
    # 多模块项目的 surefire 报告分散在各模块 target/ 下，需要递归
    return glob.glob(os.path.join(TESTBED, "**", "surefire-reports", "TEST-*.xml"),
                     recursive=True)


def clean_surefire_reports():
    for path in surefire_xml_files():
        try:
            os.remove(path)
        except OSError:
            pass


def parse_surefire_results():
    """解析 surefire XML，返回 {(classname, testname): passed|failed|error|skipped}。

    failed = 断言失败（<failure>），error = 执行异常（<error>）。二者分开记录，
    修复循环据此区分"疑似检出"与"套件自身坏掉"。
    """
    results = {}
    for path in surefire_xml_files():
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        for tc in root.iter("testcase"):
            key = (tc.get("classname", ""), tc.get("name", ""))
            if tc.find("error") is not None:
                results[key] = "error"
            elif tc.find("failure") is not None:
                results[key] = "failed"
            elif tc.find("skipped") is not None:
                results[key] = "skipped"
            else:
                results[key] = "passed"
    return results


def diff_surefire(buggy_results, orig_results):
    """差分：检出的定义为"原代码通过 ∧ bug 版失败"。

    返回 (differential, false_positives)：真检出的用例名列表 / 误报用例名列表。
    断言失败（failed）与执行异常（error）都算"未通过"。
    """
    differential, false_positives = [], []
    for key, status in buggy_results.items():
        if status in ("passed", "skipped"):
            continue
        if orig_results.get(key) == "passed":
            differential.append(key)
        else:
            false_positives.append(key)
    return differential, false_positives


def declared_class_names(tests_src):
    return sorted(set(re.findall(r"\bclass\s+(\w+)", tests_src)))


def purge_stale_test_classes(names):
    """删除已编译的测试类文件，避免删除/替换 .java 后残留 .class 被后续运行执行。"""
    prefixes = set(names)
    for root, _dirs, files in os.walk(TESTBED):
        if f"{os.sep}target{os.sep}test-classes" not in root:
            continue
        for fn in files:
            if any(fn == f"{n}.class" or fn.startswith(f"{n}$") for n in prefixes):
                try:
                    os.remove(os.path.join(root, fn))
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# bug 生成相关的 prompt 上下文
# ---------------------------------------------------------------------------

def find_related_test_sources(entry, max_chars=6000, max_files=1):
    """在 src/test 下查找涉及该函数的既有测试源码（尽力而为）。

    让 bug 生成器看到"必须保持通过"的测试，从源头提高逃逸率
    （旧 prompt 要求保持测试通过却不给看测试）。
    """
    name = (entry.get("name") or "").strip()
    if len(name) < 4:
        return ""
    test_root = os.path.join(TESTBED, "src", "test")
    if not os.path.isdir(test_root):
        test_root = os.path.join(TESTBED, "src", "test", "java")
        if not os.path.isdir(test_root):
            return ""
    snippets = []
    for dirpath, _dirnames, filenames in os.walk(test_root):
        for fn in filenames:
            if not fn.endswith(".java"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                content = open(path, "r", encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            if name in content:
                snippets.append(content[:max_chars])
                if len(snippets) >= max_files:
                    return "\n\n".join(snippets)
    return "\n\n".join(snippets)


# ---------------------------------------------------------------------------
# 各阶段
# ---------------------------------------------------------------------------

def compile_bug(bug_agent, src_file, original_code, bug_code, fix_attempts=3):
    """编译注入 bug 后的源码，失败时调用模型修复。返回 (ok, 最终bug代码, 错误信息)。"""
    last_error = ""
    for compile_attempt in range(fix_attempts + 1):
        # mvn(["spotless:apply"], timeout=600)
        result = mvn(["compile"], timeout=1800, source_path=src_file)
        if result.returncode == 0:
            return True, bug_code, ""
        last_error = maven_compile_diagnostics(
            (result.stdout or "") + (result.stderr or ""))
        # The final failed compilation has no remaining verification round.
        # Do not spend an LLM call on a repair that cannot be recompiled.
        if compile_attempt >= fix_attempts:
            break
        fixed = bug_agent.fix_bug_prompt(bug_code, last_error)
        if not fixed or fixed == bug_code:
            break
        if not set_src_code(src_file, fixed, bug_code):
            break
        bug_code = fixed
    return False, bug_code, last_error[-4000:]


def compile_test_suite(agent, test_file, tests):
    """Compile a suite, applying only safe deterministic fixes.

    Model repairs deliberately live in ``evaluate_filter_model`` so a single
    five-call budget is shared by compile failures and runtime test errors.
    Source-backed import/spelling repairs are local deterministic transforms
    and do not consume that model budget.
    """
    last_error = ""
    auto_rounds = 0
    auto_repairs = []
    while True:
        # 先让测试生成器规范化源码；编译失败后再只对生产源码能够唯一
        # 确认的 import / 方法大小写应用确定性修复。
        if hasattr(agent, "normalize_tests"):
            tests = agent.normalize_tests(tests, test_class_name(test_file), last_error)
        purge_stale_test_classes([test_class_name(test_file)] + declared_class_names(tests))
        write_text(test_file, tests)
        # mvn(["spotless:apply"], timeout=600)
        result = mvn(["test-compile"], timeout=1800, source_path=test_file)
        if result.returncode == 0:
            return True, tests, "", auto_repairs
        last_error = maven_compile_diagnostics(
            (result.stdout or "") + (result.stderr or ""))
        print(f"测试套件编译失败，{last_error[-4000:]}")
        if auto_rounds < MAX_AUTO_COMPILE_REPAIRS:
            automatically_fixed, repairs = deterministic_test_compile_repair(tests, last_error)
            if repairs and automatically_fixed != tests:
                auto_rounds += 1
                auto_repairs.extend(repairs)
                tests = automatically_fixed
                print(f"应用 {len(repairs)} 个确定性测试修复: {repairs}")
                continue
        return False, tests, last_error[-4000:], auto_repairs


MAX_TEST_REPAIRS = 5
MAX_FILTER_TEST_SUITES = 2


_TRIVIAL_TEST_PATTERNS = (
    (re.compile(r"\b(?:[A-Za-z_$][\w$]*\.)?assertTrue\s*\(\s*"
                r"(?:true|Boolean\.TRUE)\s*(?:[,)]|$)", re.IGNORECASE),
     "assertTrue(true)"),
    (re.compile(r"\b(?:[A-Za-z_$][\w$]*\.)?assertFalse\s*\(\s*"
                r"(?:false|Boolean\.FALSE)\s*(?:[,)]|$)", re.IGNORECASE),
     "assertFalse(false)"),
    (re.compile(r"\b(?:[A-Za-z_$][\w$]*\.)?assertEquals\s*\(\s*"
                r"true\s*,\s*true\s*(?:[,)]|$)", re.IGNORECASE),
     "assertEquals(true, true)"),
    (re.compile(r"\b(?:[A-Za-z_$][\w$]*\.)?assertEquals\s*\(\s*"
                r"false\s*,\s*false\s*(?:[,)]|$)", re.IGNORECASE),
     "assertEquals(false, false)"),
    (re.compile(r"\b(?:placeholder|actual\s+test\s+logic\s+would\s+go\s+here|"
                r"actual\s+implementation\s+needed)\b", re.IGNORECASE),
     "placeholder test content"),
)


def trivial_test_violation(tests: str) -> str | None:
    """Return a reason when a suite contains a plainly vacuous test.

    Surefire correctly counts ``@Test void x() { assertTrue(true); }`` as an
    executed test, so the empty-suite check cannot reject it.  These patterns
    are deliberately limited to unambiguous tautologies/placeholder text;
    semantic adequacy remains the filtering model's responsibility.
    """
    for pattern, reason in _TRIVIAL_TEST_PATTERNS:
        if pattern.search(tests or ""):
            return reason
    return None


def evaluate_filter_model(agent, entry, bug_code, src_file, original_code,
                          test_file, suite_retries=1, initial_tests=None):
    """用一个过滤模型评估当前 bug（Stage 2 单模型分支）。

    每个模型最多生成两套独立测试。普通生成器中，每套测试的编译错误和
    运行时基础设施错误共用五次模型修复额度。连续 Bash agent 已在单次
    会话内自行编译和修复，外层只独立验证一次，不再启动额外修复会话。
    两套都不可用时，直接放弃当前 bug 候选。
    断言失败是检出证据，绝不作为测试修复对象。

    每轮先过编译闸门（compile_test_suite 只做确定性修复），再运行并按
    surefire 失败类型分流（协议约定：不跑原代码做差分仲裁）——
    - 全部通过 → bug 逃逸（undetected=True）；
    - 断言失败（failure）→ 过滤模型检出 bug，立即返回，绝不修复断言；
    - 执行异常（error）/空套件 → 套件自身问题，修复后进下一轮；
    - 修复后的代码下一轮重新过编译闸门，编译错误先由确定性规则、
      后由 fix_compile 处理。

    返回 (undetected, tests, info)：
    - undetected=True ：套件在 bug 版上全部通过 → 未检出；
    - undetected=False 且 info["detected"]=True ：断言失败视为检出；
    - undetected=False 且 info["detected"]=False ：套件本身失败（编译不过/空/纯异常未修复）。
    """
    total_false_positives = None
    last_compile_error = ""
    auto_repairs = []
    suite_diagnostics = []
    last_tests = ""
    # ``suite_retries`` is retained for CLI compatibility, but the agreed
    # policy permits at most one fresh rewrite after the initial suite.
    # Resume mode supplies the final suite preserved by an earlier run.  It
    # has already consumed that model's independent-suite budget, so validate
    # and, if needed, repair only this suite instead of generating another.
    suite_count = (1 if initial_tests is not None else
                   min(MAX_FILTER_TEST_SUITES, max(1, int(suite_retries) + 1)))
    self_managed_repairs = bool(getattr(agent, "self_managed_repairs", False))
    for suite_index in range(1, suite_count + 1):
        tests = initial_tests if initial_tests is not None else agent.generate_tests(entry, bug_code)
        if not tests:
            suite_diagnostics.append({
                "suite": suite_index,
                "repair_attempts": 0,
                "reason": "test_generation_empty",
            })
            continue

        repair_attempts = 0
        suite_error = ""
        while True:
            violation = trivial_test_violation(tests)
            if violation:
                suite_error = f"rejected trivial test: {violation}"
                print(f"测试套件无效，{suite_error}")
                break
            compile_ok, tests, compile_err, compile_auto_repairs = compile_test_suite(
                agent, test_file, tests)
            auto_repairs.extend(compile_auto_repairs)
            if not compile_ok:
                print(f"测试套件编译失败，{compile_err}")
                last_compile_error = compile_err
                suite_error = compile_err
                if self_managed_repairs:
                    suite_error = "bash agent submission failed independent compilation: " + compile_err
                    break
                if repair_attempts >= MAX_TEST_REPAIRS:
                    break
                fixed = agent.fix_compile(tests, compile_err)
                repair_attempts += 1
                if not fixed or fixed == tests:
                    suite_error = "test compile repair returned no change"
                    break
                tests = fixed
                continue

            clean_surefire_reports()
            # compile_test_suite has just passed ``mvn test-compile``. Calling
            # the lifecycle phase ``test`` here would compile again even though
            # neither sources nor classpath changed.
            buggy_run = run_compiled_test(
                test_class_name(test_file), test_file=test_file, timeout=1800)
            buggy_results = parse_surefire_results()
            executed = {k: s for k, s in buggy_results.items() if s != "skipped"}

            if buggy_run.returncode == 0 and executed:
                return True, tests, {"detected": False, "total_cases": len(executed),
                                     "note": "passed_on_buggy",
                                     "auto_repairs": auto_repairs,
                                     "suite": suite_index,
                                     "repair_attempts": repair_attempts,
                                     "suite_diagnostics": suite_diagnostics + [{
                                         "suite": suite_index,
                                         "repair_attempts": repair_attempts,
                                         "reason": "passed_on_buggy",
                                     }]}

            failures = [k for k, s in executed.items() if s == "failed"]
            if failures:
                # 断言失败 → 过滤模型检出 bug（协议约定，不做差分仲裁）
                names = ", ".join(f"{c}.{n}" for c, n in failures)
                print(f"过滤模型检出 bug（断言失败）: {names}")
                return False, tests, {"detected": True, "total_cases": len(executed),
                                      "false_positives": total_false_positives,
                                      "note": f"detected_by: {names}",
                                      "auto_repairs": auto_repairs,
                                      "suite": suite_index,
                                      "repair_attempts": repair_attempts,
                                      "suite_diagnostics": suite_diagnostics + [{
                                          "suite": suite_index,
                                          "repair_attempts": repair_attempts,
                                          "reason": "detected_by_filter",
                                      }],
                                      "feedback": ((buggy_run.stdout or "") +
                                                   (buggy_run.stderr or ""))[-6000:]}

            if not executed:
                feedback = ((buggy_run.stdout or "") + (buggy_run.stderr or ""))[-4000:] \
                    or "no tests were executed"
                print(f"测试套件未执行任何用例，{feedback}")
            else:
                errors = [k for k, s in executed.items() if s == "error"]
                names = ", ".join(f"{c}.{n}" for c, n in errors)
                feedback = (buggy_run.stdout or "") + (buggy_run.stderr or "")
                print(f"测试套件存在 {len(errors)} 个执行异常，修复后重试: {names}")

            suite_error = feedback[-4000:]
            if self_managed_repairs:
                suite_error = "bash agent submission failed independent runtime verification: " + suite_error
                break
            if repair_attempts >= MAX_TEST_REPAIRS:
                break
            fixed = agent.repair_tests(tests, feedback)
            repair_attempts += 1
            if not fixed or fixed == tests:
                suite_error = "test runtime repair returned no change"
                break
            tests = fixed

        last_tests = tests
        suite_diagnostics.append({
            "suite": suite_index,
            "repair_attempts": repair_attempts,
            "reason": suite_error or "test_suite_unusable",
        })

    return False, last_tests, {"detected": False, "total_cases": 0,
                               "false_positives": total_false_positives,
                               "note": "suite_generation_failed",
                               "auto_repairs": auto_repairs,
                               "compile_error": last_compile_error,
                               "suite_diagnostics": suite_diagnostics}


def process_entry(entry, agents, opts):
    """处理单个函数条目。返回 (accepted: bool, attempt_traces: list)。"""
    code = entry.get("code", "")
    src_file = entry.get("src_file", "")
    test_file = entry.get("test_file", "")
    test_class = test_class_name(test_file) if test_file else ""
    # tests_context = find_related_test_sources(entry)

    # 保留完整文件快照：正常分支仍在每次尝试后就地恢复，而这里的
    # finally 负责覆盖 LLM/API/XML/文件系统异常等意外中断。
    original_source_file = read_text(src_file)
    test_existed = bool(test_file) and os.path.isfile(test_file)
    original_test_file = read_text(test_file) if test_existed else None

    current_bug = ""
    retry_request = None
    attempt_traces = []
    bug_summary_history = []

    try:
        for attempt in range(opts.attempts):
            trace = {"attempt": attempt + 1}

            # ---- Stage 1：生成一个新的 bug 候选 ----
            # ``attempts`` 只计不同 bug 候选；测试套件失败不复用旧 bug
            # 重跑完整过滤流程。
            if retry_request is None:
                bug_json = agents["bug"].init_bug_prompt(
                    code, entry.get("specification", ""), context=entry)
            elif retry_request["kind"] == "detected_by_filter":
                bug_json = agents["bug"].enhance_bug_prompt(
                    code, retry_request["bug_code"], retry_request["feedback"],
                    entry.get("specification", ""), context=entry,
                    test_source=retry_request["test_source"],
                    previous_summaries=bug_summary_history)
            else:
                bug_json = agents["bug"].retry_bug_prompt(
                    code, retry_request.get("bug_code", ""),
                    retry_request["feedback"], entry.get("specification", ""),
                    context=entry, previous_summaries=bug_summary_history)
            if not isinstance(bug_json, dict):
                print(f"bug 生成失败，返回非字典")
                trace["outcome"] = "bug_generation_error"
                attempt_traces.append(trace)
                retry_request = None
                continue
            current_bug = (bug_json.get("buggy_code") or "").strip()
            bug_summary = bug_json.get("bug_summary", "")
            if not current_bug or current_bug == code:
                trace["outcome"] = "bug_generation_empty"
                attempt_traces.append(trace)
                retry_request = None
                continue

            # 记录模型初次生成的 bug 代码（便于事后对比修复前后）
            trace["bug_code"] = _truncate(current_bug)
            trace["bug_summary"] = bug_summary
            if str(bug_summary or "").strip():
                bug_summary_history.append(str(bug_summary).strip())

            if not set_src_code(src_file, current_bug, code):
                trace["outcome"] = "patch_failed"
                attempt_traces.append(trace)
                retry_request = {
                    "kind": "generation_or_patch_failure",
                    "bug_code": current_bug,
                    "feedback": "The candidate could not be applied as a unique replacement in the source file. Generate a drop-in replacement for exactly the supplied code unit.",
                }
                continue

            compile_ok, current_bug, compile_err = compile_bug(
                agents["bug"], src_file, code, current_bug)

            # 编译修复后，bug 代码可能变化，覆盖为实际拿去过滤的版本
            trace["bug_code"] = _truncate(current_bug)
            trace["bug_code_after_compile_fix"] = _truncate(current_bug)

            print("------------------------------------------------------------------")
            if not compile_ok:
                print(f"compile_error: {compile_err}")
                write_text(src_file, original_source_file)
                trace["outcome"] = "compile_failed"
                trace["compile_error"] = compile_err
                attempt_traces.append(trace)
                retry_request = {
                    "kind": "compile_failed",
                    "bug_code": current_bug,
                    "feedback": f"The previous candidate could not be compiled after repair attempts. Compiler feedback:\n{compile_err}",
                }
                continue

            # ---- Stage 2：双模型过滤 ----
            filter_results = {}
            suites = {}
            accepted_phase2 = True
            phase2_reason = ""
            for model_key in ("model_a", "model_b"):
                # A continuous Bash agent is allowed to explore freely, but
                # its edits to production code must never affect the outer
                # filter verdict.  Restore the already-compiled buggy tree
                # before compiling/running its returned test suite.
                production_snapshot = snapshot_production_sources()
                try:
                    undetected, suite_tests, info = evaluate_filter_model(
                        agents[model_key], entry, current_bug, src_file, code,
                        test_file, opts.suite_retries)
                finally:
                    restore_production_sources(production_snapshot)
                info["model"] = agents[model_key].model_name
                filter_results[model_key] = info
                suites[model_key] = suite_tests
                # 写入 trace：过滤模型 info（去掉冗长 feedback）+ 最终生成的测试套件
                trace[model_key] = {k: v for k, v in info.items() if k != "feedback"}
                trace[model_key]["generated_tests"] = _truncate(suite_tests)
                if info["detected"]:
                    accepted_phase2 = False
                    phase2_reason = "detected_by_filter"
                    retry_request = {
                        "kind": "detected_by_filter",
                        "bug_code": current_bug,
                        "feedback": f"{info['note']}\n{info.get('feedback', '')}",
                        "test_source": suite_tests,
                    }
                    break
                if not undetected:
                    accepted_phase2 = False
                    phase2_reason = "suite_generation_failed"
                    retry_request = {
                        "kind": "suite_generation_failed",
                        "bug_code": current_bug,
                        "feedback": (
                            "The filter model could not produce an executable suite after its "
                            "allowed independent suite attempts. This is not evidence that the bug "
                            "was detected. Generate a fresh, different candidate.\n"
                            f"{info['note']}\n{info.get('compile_error', '')}"
                        ),
                    }
                    break
            if not accepted_phase2:
                write_text(src_file, original_source_file)
                if test_file and os.path.exists(test_file):
                    os.remove(test_file)
                trace["outcome"] = phase2_reason
                attempt_traces.append(trace)
                continue

        # ---- Stage 3：原测试套件作为元数据（不过滤）----
        # purge_stale_test_classes([test_class] + declared_class_names(suites["model_a"])
        #                          + declared_class_names(suites["model_b"]))
        # if test_file and os.path.exists(test_file):
        #     os.remove(test_file)  # 过滤套件不参与原套件运行
        # clean_surefire_reports()
        # full_run = mvn(["test"], timeout=3600)
        # full_results = parse_surefire_results()
        # escaped = full_run.returncode == 0
        # original_failing = [f"{c}.{n}" for (c, n), s in full_results.items() if s == "failed"]
        # trace["original_suite"] = {"escaped": escaped, "failing": original_failing}

            # ---- Stage 4：等效判定（沿用语义行为一致性）----
            validation = agents["judge"].validate(
                code, current_bug, (suites["model_a"] + "\n\n" + suites["model_b"]).strip())
            if not isinstance(validation, dict):
                validation = {"is_valid_bug": False, "reason": "judge returned non-dict"}

            # 还原项目状态
            write_text(src_file, original_source_file)
            if test_file and os.path.exists(test_file):
                os.remove(test_file)

            # 只接受 JSON boolean true；字符串 "false" 不能被 Python 当作真值。
            is_valid_bug = validation.get("is_valid_bug") is True
            trace["outcome"] = "accepted" if is_valid_bug else "equivalent_mutation"
            attempt_traces.append(trace)

            if is_valid_bug:
                return True, {
                    "bug_code": current_bug,
                    "bug_summary": bug_summary,
                    "suites": suites,
                    "filter_results": filter_results,
                    # "escaped_original_suite": escaped,
                    # "original_failing_tests": original_failing,
                    "validation": validation,
                }, attempt_traces

            retry_request = {
                "kind": "equivalent_mutation",
                "bug_code": current_bug,
                "feedback": (
                    "The semantic judge rejected the previous candidate as equivalent or not a "
                    "meaningful reachable bug. Generate a different candidate with a concrete "
                    f"observable behavioral difference. Judge feedback: {validation.get('reason', '')}"
                ),
            }

        return False, {}, attempt_traces
    finally:
        write_text(src_file, original_source_file)
        if test_file:
            if test_existed:
                write_text(test_file, original_test_file)
            elif os.path.exists(test_file):
                os.remove(test_file)
        if test_class:
            purge_stale_test_classes([test_class])


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def write_json_atomic(path, value):
    """先写同目录临时文件再替换，避免中断时留下半个 JSON。"""
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=4)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)


def persist_outputs(results_path, stats_path, results_dir, final_results, stats):
    """无论是否有接受项，都持久化结果和完整轨迹。"""
    write_json_atomic(results_path, final_results)
    write_json_atomic(stats_path, stats)
    os.makedirs(results_dir, exist_ok=True)
    for source in (results_path, stats_path):
        target = os.path.join(results_dir, os.path.basename(source))
        if os.path.abspath(source) != os.path.abspath(target):
            shutil.copy2(source, target)

def main(args):
    # Keep credentials separate by provider. LLM_API_KEY remains a GPT-side
    # compatibility fallback for existing single-provider direct invocations.
    gpt_api_key = os.getenv("GPT_API_KEY") or os.getenv("LLM_API_KEY")
    qwen_api_key = os.getenv("QWEN_API_KEY")
    gpt_endpoint = args.gpt_api_endpoint or os.getenv(
        "GPT_API_ENDPOINT", DEFAULT_GPT_ENDPOINT)
    # OpenRouter model IDs are provider-qualified (for example
    # ``qwen/qwen3-coder-30b-a3b-instruct``).  Select its endpoint by
    # default so that a correctly configured QWEN_API_KEY cannot
    # accidentally be sent to the legacy Qianwen-compatible gateway.
    qwen_endpoint = args.qwen_api_endpoint or os.getenv("QWEN_API_ENDPOINT")
    if not qwen_endpoint:
        qwen_endpoint = (OPENROUTER_ENDPOINT
                         if args.filter_model_b.startswith("qwen/")
                         else DEFAULT_QWEN_ENDPOINT)
    if not gpt_api_key:
        raise RuntimeError("未设置 GPT_API_KEY（或兼容的 LLM_API_KEY）")
    model_b_uses_gpt = uses_gpt_provider(args.filter_model_b)
    if not model_b_uses_gpt and not qwen_api_key:
        raise RuntimeError("未设置 QWEN_API_KEY")
    if args.attempts < 1 or args.suite_retries != 1:
        raise ValueError("attempts 必须 >= 1，suite-retries 固定为 1（两套测试）")
    if args.test_agent_steps < 1 or args.test_agent_timeout < 1:
        raise ValueError("test-agent-steps 和 test-agent-timeout 必须 >= 1")

    if args.test_agent == "mini-swe":
        # Keep the legacy restricted mode usable in images that do not mount
        # mini-SWE's runtime dependencies.
        from mini_swe_test_agent import MiniSweTestAgent
        filter_agent_class = MiniSweTestAgent
    else:
        filter_agent_class = FilterTestGenerationAgent
    filter_agent_kwargs = ({"step_limit": args.test_agent_steps,
                            "wall_time_limit": args.test_agent_timeout}
                           if args.test_agent == "mini-swe" else {})
    model_b_api_key = gpt_api_key if model_b_uses_gpt else qwen_api_key
    model_b_endpoint = gpt_endpoint if model_b_uses_gpt else qwen_endpoint
    agents = {
        "bug": BugGenerationAgent(LLMConfig(gpt_api_key, gpt_endpoint, args.bug_model)),
        "judge": ValidAgent(LLMConfig(gpt_api_key, gpt_endpoint, args.judge_model)),
        "model_a": (filter_agent_class(
            LLMConfig(gpt_api_key, gpt_endpoint, args.filter_model_a), **filter_agent_kwargs)
            if args.test_agent == "mini-swe" else filter_agent_class(
                LLMConfig(gpt_api_key, gpt_endpoint, args.filter_model_a), args.suite_retries)),
        "model_b": (filter_agent_class(
            LLMConfig(model_b_api_key, model_b_endpoint, args.filter_model_b), **filter_agent_kwargs)
            if args.test_agent == "mini-swe" else filter_agent_class(
                LLMConfig(model_b_api_key, model_b_endpoint, args.filter_model_b), args.suite_retries)),
    }
    print(f"bug 模型: {args.bug_model} | 等效判定: {args.judge_model} | "
          f"过滤模型: {args.filter_model_a} / {args.filter_model_b} | "
          f"测试智能体: {args.test_agent}")

    with open(args.data_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("输入 JSON 顶层必须是函数条目列表")
    if args.start_index < 0 or args.limit < 0:
        raise ValueError("start-index 和 limit 必须 >= 0")
    total_entries = len(data)
    if args.limit:
        data = data[args.start_index:args.start_index + args.limit]
    else:
        data = data[args.start_index:]
    if args.start_index or args.limit:
        print(f"抽样运行：原始 {total_entries} 条，处理索引 "
              f"[{args.start_index}, {args.start_index + len(data)})")
    print(f"共 {len(data)} 个函数待处理")

    delete_test_files_in_test_dirs(TESTBED)

    final_results = []
    stats = []
    # 先写空结果，保证“零接受”也是一个明确、可区分于运行失败的结果。
    persist_outputs(args.results_path, args.stats_path, args.results_dir,
                    final_results, stats)
    for idx, entry in enumerate(data):
        name = entry.get("name", f"entry_{idx}")
        print(f"\n===== [{idx + 1}/{len(data)}] {name} =====")
        if not entry.get("code") or not entry.get("src_file") or not entry.get("test_file"):
            stats.append({"name": name, "status": "skipped_missing_fields"})
            persist_outputs(args.results_path, args.stats_path, args.results_dir,
                            final_results, stats)
            continue

        try:
            usage_tracker.reset()
            started_at = time.perf_counter()
            accepted, accepted_data, traces = process_entry(entry, agents, args)
        except Exception as e:
            print(f"条目处理异常: {type(e).__name__}: {e}")
            stats.append({"name": name, "status": "processing_error",
                          "error_type": type(e).__name__, "error": str(e),
                          "elapsed_seconds": round(time.perf_counter() - started_at, 3),
                          "llm_usage": usage_tracker.summary()})
            persist_outputs(args.results_path, args.stats_path, args.results_dir,
                            final_results, stats)
            continue
        outcome = traces[-1]["outcome"] if traces else "no_attempts"

        stats.append({"name": name, "status": "accepted" if accepted else outcome,
                      "elapsed_seconds": round(time.perf_counter() - started_at, 3),
                      "llm_usage": usage_tracker.summary(), "attempts": traces})

        if accepted:
            entry["buggy_code"] = [accepted_data["bug_code"]]
            entry["tests"] = [accepted_data["suites"]["model_a"],
                              accepted_data["suites"]["model_b"]]
            entry["bug_summary"] = accepted_data["bug_summary"]
            entry["flag"] = "dual_filter_pass"
            entry["status"] = "accepted"
            entry["filter_results"] = accepted_data["filter_results"]
            # entry["escaped_original_suite"] = accepted_data["escaped_original_suite"]
            # entry["original_failing_tests"] = accepted_data["original_failing_tests"]
            entry["validation_result"] = accepted_data["validation"]
            entry["filter_attempts"] = len(traces)
            final_results.append(entry)
            print(f"已接受错误代码（尝试 {len(traces)} 次）:\n{accepted_data['bug_code'][:500]}")
        else:
            entry["flag"] = "not_accepted"
            entry["status"] = outcome
            entry["filter_attempts"] = len(traces)
            print(f"未接受（{outcome}，尝试 {len(traces)} 次）")

        persist_outputs(args.results_path, args.stats_path, args.results_dir,
                        final_results, stats)

    print(f"\n完成：接受 {len(final_results)}/{len(data)} 条。"
          f"明细见 {args.results_path} / {args.stats_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="双大模型过滤的错误代码生成流程（Java/Maven）")
    parser.add_argument("--data-path", type=str, required=True,
                        help="输入 JSON 数据文件路径（需含 specification 字段）")
    parser.add_argument("--bug-model", type=str, default="gpt-5-nano",
                        help="bug 生成模型")
    parser.add_argument("--judge-model", type=str, default="gpt-5-nano",
                        help="等效判定模型")
    parser.add_argument("--filter-model-a", type=str, default="gpt-5-nano",
                        help="过滤模型 A（应与被评测模型不同厂商/代际）")
    parser.add_argument("--filter-model-b", type=str, default="qwen3.5-flash",
                        help="过滤模型 B")
    parser.add_argument("--gpt-api-endpoint", type=str, default=None,
                        help="GPT 角色 endpoint；默认读取 GPT_API_ENDPOINT 或 Agicto")
    parser.add_argument("--qwen-api-endpoint", type=str, default=None,
                        help="Qwen 过滤角色 endpoint；默认读取 QWEN_API_ENDPOINT；qwen/ 模型自动使用 OpenRouter")
    parser.add_argument("--attempts", type=int, default=3,
                        help="每个函数的 bug 对抗尝试次数上限")
    parser.add_argument("--suite-retries", type=int, default=1, choices=(1,),
                        help="固定为 1：每个过滤模型生成初始测试并重写一次，共两套测试")
    parser.add_argument("--test-agent", choices=("mini-swe", "restricted"), default="mini-swe",
                        help="测试生成器；mini-swe 使用连续 Bash 会话，restricted 保留旧受限搜索模式")
    parser.add_argument("--test-agent-steps", type=int, default=100,
                        help="mini-swe 单次生成或修复会话的最大模型调用数")
    parser.add_argument("--test-agent-timeout", type=int, default=1200,
                        help="mini-swe 单次生成或修复会话的总时限（秒）")
    parser.add_argument("--start-index", type=int, default=0,
                        help="从输入数据的指定零基索引开始处理")
    parser.add_argument("--limit", type=int, default=0,
                        help="最多处理的条目数；0 表示处理到末尾")
    parser.add_argument("--results-path", type=str, default="/testbed/final_results.json")
    parser.add_argument("--stats-path", type=str, default="/testbed/filter_stats.json")
    parser.add_argument("--results-dir", type=str, default="/results")
    main(parser.parse_args())

# """
# adver_dual.py —— 双大模型过滤的错误代码生成流程。

# 与 adver.py（旧流程）的区别（详见分析报告）：
# 1. 删除"原测试套件"过滤闸门，改由两个不同厂商的大模型按评测协议生成测试并过滤；
#    原测试套件降级为元数据：验收时跑一次，记录 escaped_original_suite / 失败用例，
#    被其检出即作为"非等效"的强证据。
# 2. 过滤协议与评测管线同源：复用 gen_test/llm_gentests.py 的 TestCodeGenerator
#    （specification 模式模板、temperature=0、max_K=3 重试），输入为"错误代码 + 规范"，
#    与被评测模型看到的信息一致——过滤准则即"在评测协议下该模型未检出此 bug"。
# 3. 只在错误代码上运行过滤测试，按 surefire 失败类型分流（不跑原代码做差分）：
#    - 断言失败（failure）= 过滤模型检出 bug → 反馈给 bug 生成器重试；
#    - 执行异常（error）→ 迭代修复测试套件，bug 保留；
#    - 编译始终失败 / 空套件 = 套件问题 → 重新生成套件，不判检出。
# 4. 等效判定沿用 valid_agent.py 的语义行为一致性判定。

# 用法（容器内，WORKDIR=/testbed 为项目根目录）：
#     python3 /testbed/adver_dual.py --data-path /testbed/<data>.json \
#         --filter-model-a deepseek-v3.2 --filter-model-b qwen3-coder-480b-a35b-instruct

# 建议通过环境变量 LLM_API_KEY / LLM_API_ENDPOINT 配置凭证（未设置时回退到
# 历史内置 key，仅供过渡；该 key 已出现在仓库历史中，应尽快吊销轮换）。

# 输出：
#     /testbed/final_results.json   仅收录被接受的条目（ schema 与旧流程兼容，额外字段见下）
#     /testbed/filter_stats.json    全部条目的尝试轨迹（用于新旧流程 A/B 对比）
# """

# import argparse
# import glob
# import json
# import os
# import re
# import shutil
# import subprocess
# import xml.etree.ElementTree as ET
# from pathlib import Path

# from llm_config import LLMConfig
# from bug_generation_agent import BugGenerationAgent
# from valid_agent import ValidAgent
# from filter_test_gen import FilterTestGenerationAgent

# TESTBED = "/testbed"
# MVN_SKIP_ARGS = ["-Drat.skip=true", "-Dformatter.skip=true", "-DforkCount=0"]

# Historical embedded API key removed; credentials must come from LLM_API_KEY.
# DEFAULT_ENDPOINT = "https://api.apiyi.com/v1"


# # ---------------------------------------------------------------------------
# # 基础工具
# # ---------------------------------------------------------------------------

# def sh(cmd, timeout=1800):
#     try:
#         return subprocess.run(cmd, cwd=TESTBED, capture_output=True, text=True,
#                               timeout=timeout)
#     except subprocess.TimeoutExpired as e:
#         out = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode("utf-8", "ignore")
#         err = e.stderr if isinstance(e.stderr, str) else (e.stderr or b"").decode("utf-8", "ignore")
#         return subprocess.CompletedProcess(cmd, returncode=-1, stdout=out, stderr=err)


# def mvn(goal_args, timeout=1800):
#     return sh(["mvn"] + goal_args + MVN_SKIP_ARGS, timeout=timeout)


# def read_text(path):
#     with open(path, "r", encoding="utf-8") as f:
#         return f.read()


# def write_text(path, content):
#     d = os.path.dirname(path)
#     if d:
#         os.makedirs(d, exist_ok=True)
#     with open(path, "w", encoding="utf-8") as f:
#         f.write(content)


# def set_src_code(src_file, new_code, old_code):
#     """把 src_file 中的 old_code 片段替换为 new_code。返回是否替换成功。"""
#     src = read_text(src_file)
#     if old_code not in src:
#         return False
#     write_text(src_file, src.replace(old_code, new_code))
#     return True


# def test_class_name(test_file):
#     return os.path.splitext(os.path.basename(test_file))[0]

# def delete_test_files_in_test_dirs(project_root):
#     """在 test/tests 目录中删除 *test*.java 文件"""
#     # 查找 test/tests 目录
#     test_dirs = []
#     for root, dirs, files in os.walk(project_root):
#         root_path = Path(root)

#         # 跳过某些目录
#         skip_dirs = ['.git', 'venv', '.venv', '__pycache__']
#         if any(skip in root_path.parts for skip in skip_dirs):
#             continue

#         # 如果是 test 或 tests 目录
#         if root_path.name.lower() in ['test', 'tests']:
#             test_dirs.append(root_path)

#     if not test_dirs:
#         print("未找到 test 或 tests 目录")
#         return

#     # 查找并删除测试文件
#     deleted_files = []
#     for test_dir in test_dirs:
#         for file in test_dir.rglob('*.java'):
#             # if 'Test' in file.name:
#             try:
#                 os.remove(file)
#                 deleted_files.append(file)
#             except Exception as e:
#                 print(f"删除失败 {file}: {e}")

#     # 显示结果
#     print(f"在 {len(test_dirs)} 个测试目录中删除了 {len(deleted_files)} 个测试文件:")
#     for file in deleted_files[:10]:
#         print(f"  {file}")

#     if len(deleted_files) > 10:
#         print(f"  ... 还有 {len(deleted_files)-10} 个文件")



# # ---------------------------------------------------------------------------
# # Surefire 结果解析（per-test 差分仲裁）
# # ---------------------------------------------------------------------------

# def surefire_xml_files():
#     # 多模块项目的 surefire 报告分散在各模块 target/ 下，需要递归
#     return glob.glob(os.path.join(TESTBED, "**", "surefire-reports", "TEST-*.xml"),
#                      recursive=True)


# def clean_surefire_reports():
#     for path in surefire_xml_files():
#         try:
#             os.remove(path)
#         except OSError:
#             pass


# def parse_surefire_results():
#     """解析 surefire XML，返回 {(classname, testname): passed|failed|error|skipped}。

#     failed = 断言失败（<failure>），error = 执行异常（<error>）。二者分开记录，
#     修复循环据此区分"疑似检出"与"套件自身坏掉"。
#     """
#     results = {}
#     for path in surefire_xml_files():
#         try:
#             root = ET.parse(path).getroot()
#         except ET.ParseError:
#             continue
#         for tc in root.iter("testcase"):
#             key = (tc.get("classname", ""), tc.get("name", ""))
#             if tc.find("error") is not None:
#                 results[key] = "error"
#             elif tc.find("failure") is not None:
#                 results[key] = "failed"
#             elif tc.find("skipped") is not None:
#                 results[key] = "skipped"
#             else:
#                 results[key] = "passed"
#     return results


# def diff_surefire(buggy_results, orig_results):
#     """差分：检出的定义为"原代码通过 ∧ bug 版失败"。

#     返回 (differential, false_positives)：真检出的用例名列表 / 误报用例名列表。
#     断言失败（failed）与执行异常（error）都算"未通过"。
#     """
#     differential, false_positives = [], []
#     for key, status in buggy_results.items():
#         if status in ("passed", "skipped"):
#             continue
#         if orig_results.get(key) == "passed":
#             differential.append(key)
#         else:
#             false_positives.append(key)
#     return differential, false_positives


# def declared_class_names(tests_src):
#     return sorted(set(re.findall(r"\bclass\s+(\w+)", tests_src)))


# def purge_stale_test_classes(names):
#     """删除已编译的测试类文件，避免删除/替换 .java 后残留 .class 被后续运行执行。"""
#     prefixes = set(names)
#     for root, _dirs, files in os.walk(TESTBED):
#         if f"{os.sep}target{os.sep}test-classes" not in root:
#             continue
#         for fn in files:
#             if any(fn == f"{n}.class" or fn.startswith(f"{n}$") for n in prefixes):
#                 try:
#                     os.remove(os.path.join(root, fn))
#                 except OSError:
#                     pass


# # ---------------------------------------------------------------------------
# # bug 生成相关的 prompt 上下文
# # ---------------------------------------------------------------------------

# def find_related_test_sources(entry, max_chars=6000, max_files=1):
#     """在 src/test 下查找涉及该函数的既有测试源码（尽力而为）。

#     让 bug 生成器看到"必须保持通过"的测试，从源头提高逃逸率
#     （旧 prompt 要求保持测试通过却不给看测试）。
#     """
#     name = (entry.get("name") or "").strip()
#     if len(name) < 4:
#         return ""
#     test_root = os.path.join(TESTBED, "src", "test")
#     if not os.path.isdir(test_root):
#         test_root = os.path.join(TESTBED, "src", "test", "java")
#         if not os.path.isdir(test_root):
#             return ""
#     snippets = []
#     for dirpath, _dirnames, filenames in os.walk(test_root):
#         for fn in filenames:
#             if not fn.endswith(".java"):
#                 continue
#             path = os.path.join(dirpath, fn)
#             try:
#                 content = open(path, "r", encoding="utf-8", errors="ignore").read()
#             except OSError:
#                 continue
#             if name in content:
#                 snippets.append(content[:max_chars])
#                 if len(snippets) >= max_files:
#                     return "\n\n".join(snippets)
#     return "\n\n".join(snippets)


# # ---------------------------------------------------------------------------
# # 各阶段
# # ---------------------------------------------------------------------------

# def compile_bug(bug_agent, src_file, original_code, bug_code, fix_attempts=3):
#     """编译注入 bug 后的源码，失败时调用模型修复。返回 (ok, 最终bug代码, 错误信息)。"""
#     last_error = ""
#     for _ in range(fix_attempts + 1):
#         result = mvn(["compile"], timeout=1800)
#         if result.returncode == 0:
#             return True, bug_code, ""
#         last_error = result.stdout
#         fixed = bug_agent.fix_bug_prompt(bug_code, result.stdout)
#         if not fixed or fixed == bug_code:
#             break
#         if not set_src_code(src_file, fixed, bug_code):
#             break
#         bug_code = fixed
#     return False, bug_code, last_error[-4000:]


# def compile_test_suite(agent, test_file, tests, fix_attempts=5):
#     """编译测试套件，失败时调用模型修复。返回 (ok, 最终测试代码, 错误信息)。"""
#     last_error = ""
#     for _ in range(fix_attempts + 1):
#         purge_stale_test_classes([test_class_name(test_file)] + declared_class_names(tests))
#         write_text(test_file, tests)
#         result = mvn(["test-compile"], timeout=1800)
#         if result.returncode == 0:
#             return True, tests, ""
#         last_error = result.stdout
#         print(f"测试套件编译失败，{result.stdout[-4000:]}")
#         fixed = agent.fix_compile(tests, result.stdout)
#         if not fixed or fixed == tests:
#             break
#         tests = fixed
#     return False, tests, last_error[-4000:]


# MAX_REPAIR_ROUNDS = 5  # 单个套件"编译→运行→修复"的共享轮数预算


# def evaluate_filter_model(agent, entry, bug_code, src_file, original_code,
#                           test_file, suite_retries):
#     """用一个过滤模型评估当前 bug（Stage 2 单模型分支）。

#     统一修复循环：每轮先过编译闸门（compile_test_suite 内含 fix_compile 重试），
#     再运行并按 surefire 失败类型分流（协议约定：不跑原代码做差分仲裁）——
#     - 全部通过 → bug 逃逸（undetected=True）；
#     - 断言失败（failure）→ 过滤模型检出 bug，立即返回，绝不修复断言；
#     - 执行异常（error）/空套件 → 套件自身问题，修复后进下一轮；
#     - 修复后的代码下一轮重新过编译闸门，编译错误由 fix_compile 处理。

#     返回 (undetected, tests, info)：
#     - undetected=True ：套件在 bug 版上全部通过 → 未检出；
#     - undetected=False 且 info["detected"]=True ：断言失败视为检出；
#     - undetected=False 且 info["detected"]=False ：套件本身失败（编译不过/空/纯异常未修复）。
#     """
#     tests = agent.generate_tests(entry, bug_code)
#     total_false_positives = None
#     for _suite_try in range(suite_retries + 1):
#         if not tests:
#             tests = agent.generate_tests(entry, bug_code)
#             if not tests:
#                 continue

#         for _round in range(MAX_REPAIR_ROUNDS):
#             compile_ok, tests, compile_err = compile_test_suite(agent, test_file, tests)
#             if not compile_ok:
#                 print(f"测试套件编译失败，{compile_err}")
#                 tests = ""  # 清空，触发外层重新生成
#                 break

#             clean_surefire_reports()
#             buggy_run = mvn(["test", f"-Dtest={test_class_name(test_file)}"], timeout=1800)
#             buggy_results = parse_surefire_results()
#             executed = {k: s for k, s in buggy_results.items() if s != "skipped"}

#             if buggy_run.returncode == 0 and executed:
#                 return True, tests, {"detected": False, "total_cases": len(executed),
#                                      "note": "passed_on_buggy"}

#             if not executed:
#                 # 没有任何用例真正执行（类名不匹配/全部被跳过/初始化错误）
#                 feedback = buggy_run.stdout[-4000:] or "no tests were executed"
#                 print(f"测试套件未执行任何用例，{feedback}")
#                 tests = agent.repair_tests(tests, feedback)
#                 continue

#             failures = [k for k, s in executed.items() if s == "failed"]  # 断言失败
#             errors = [k for k, s in executed.items() if s == "error"]     # 执行异常

#             if failures:
#                 # 断言失败 → 过滤模型检出 bug（协议约定，不做差分仲裁）
#                 names = ", ".join(f"{c}.{n}" for c, n in failures)
#                 print(f"过滤模型检出 bug（断言失败）: {names}")
#                 return False, tests, {"detected": True, "total_cases": len(executed),
#                                       "false_positives": total_false_positives,
#                                       "note": f"detected_by: {names}",
#                                       "feedback": buggy_run.stdout[-6000:]}

#             # 只有执行异常（error）→ 套件自身问题，迭代修复
#             err_names = ", ".join(f"{c}.{n}" for c, n in errors)
#             print(f"测试套件存在 {len(errors)} 个执行异常，修复后重试: {err_names}")
#             tests = agent.repair_tests(tests, buggy_run.stdout)

#     return False, tests or "", {"detected": False, "total_cases": 0,
#                                 "false_positives": total_false_positives,
#                                 "note": "suite_generation_failed"}


# def process_entry(entry, agents, opts):
#     """处理单个函数条目。返回 (accepted: bool, attempt_traces: list)。"""
#     code = entry.get("code", "")
#     src_file = entry.get("src_file", "")
#     test_file = entry.get("test_file", "")
#     test_class = test_class_name(test_file) if test_file else ""
#     # tests_context = find_related_test_sources(entry)

#     current_bug = ""
#     test_info = ""
#     attempt_traces = []

#     for attempt in range(opts.attempts):
#         trace = {"attempt": attempt + 1}

#         # ---- Stage 1：生成 bug（对抗循环，反馈源为过滤套件的失败输出）----
#         if attempt == 0:
#             bug_json = agents["bug"].init_bug_prompt(code)
#         else:
#             bug_json = agents["bug"].enhance_bug_prompt(
#                 code, current_bug, test_info)
#         if not isinstance(bug_json, dict):
#             print(f"bug 生成失败，返回非字典")
#             trace["outcome"] = "bug_generation_error"
#             attempt_traces.append(trace)
#             continue
#         current_bug = (bug_json.get("buggy_code") or "").strip()
#         bug_summary = bug_json.get("bug_summary", "")
#         if not current_bug or current_bug == code:
#             trace["outcome"] = "bug_generation_empty"
#             attempt_traces.append(trace)
#             continue
#         if not set_src_code(src_file, current_bug, code):
#             trace["outcome"] = "patch_failed"
#             attempt_traces.append(trace)
#             continue

#         compile_ok, current_bug, compile_err = compile_bug(
#             agents["bug"], src_file, code, current_bug)
       
#         print("------------------------------------------------------------------")
#         if not compile_ok:
#             print(f"compile_error: {compile_err}")
#             set_src_code(src_file, code, current_bug)
#             trace["outcome"] = "compile_failed"
#             trace["compile_error"] = compile_err
#             attempt_traces.append(trace)
#             continue

#         # ---- Stage 2：双模型过滤 ----
#         filter_results = {}
#         suites = {}
#         accepted_phase2 = True
#         phase2_reason = ""
#         for model_key in ("model_a", "model_b"):
#             undetected, suite_tests, info = evaluate_filter_model(
#                 agents[model_key], entry, current_bug, src_file, code,
#                 test_file, opts.suite_retries)
#             info["model"] = agents[model_key].model_name
#             filter_results[model_key] = info
#             suites[model_key] = suite_tests
#             trace[model_key] = {k: v for k, v in info.items() if k != "feedback"}
#             if info["detected"]:
#                 accepted_phase2 = False
#                 phase2_reason = "detected_by_filter"
#                 test_info = f"{info['note']}\n{info.get('feedback', '')}"
#                 break
#             if not undetected:
#                 accepted_phase2 = False
#                 phase2_reason = "suite_generation_failed"
#                 test_info = f"filter suite generation failed: {info['note']}\n{compile_err if not suite_tests else ''}"
#                 break
#         if not accepted_phase2:
#             set_src_code(src_file, code, current_bug)
#             if test_file and os.path.exists(test_file):
#                 os.remove(test_file)
#             trace["outcome"] = phase2_reason
#             attempt_traces.append(trace)
#             continue

#         # ---- Stage 3：原测试套件作为元数据（不过滤）----
#         # purge_stale_test_classes([test_class] + declared_class_names(suites["model_a"])
#         #                          + declared_class_names(suites["model_b"]))
#         # if test_file and os.path.exists(test_file):
#         #     os.remove(test_file)  # 过滤套件不参与原套件运行
#         # clean_surefire_reports()
#         # full_run = mvn(["test"], timeout=3600)
#         # full_results = parse_surefire_results()
#         # escaped = full_run.returncode == 0
#         # original_failing = [f"{c}.{n}" for (c, n), s in full_results.items() if s == "failed"]
#         # trace["original_suite"] = {"escaped": escaped, "failing": original_failing}

#         # ---- Stage 4：等效判定（沿用语义行为一致性）----
#         validation = agents["judge"].validate(
#             code, current_bug, (suites["model_a"] + "\n\n" + suites["model_b"]).strip())
#         if not isinstance(validation, dict):
#             validation = {"is_valid_bug": False, "reason": "judge returned non-dict"}

#         # 还原项目状态
#         set_src_code(src_file, code, current_bug)
#         if test_file and os.path.exists(test_file):
#             os.remove(test_file)

#         is_valid_bug = bool(validation.get("is_valid_bug", False))
#         trace["outcome"] = "accepted" if is_valid_bug else "equivalent_mutation"
#         attempt_traces.append(trace)

#         if is_valid_bug:
#             return True, {
#                 "bug_code": current_bug,
#                 "bug_summary": bug_summary,
#                 "suites": suites,
#                 "filter_results": filter_results,
#                 # "escaped_original_suite": escaped,
#                 # "original_failing_tests": original_failing,
#                 "validation": validation,
#             }, attempt_traces

#     return False, {}, attempt_traces


# # ---------------------------------------------------------------------------
# # 主流程
# # ---------------------------------------------------------------------------

# def main(args):
#     api_key = os.getenv("LLM_API_KEY", DEFAULT_API_KEY)
#     endpoint = os.getenv("LLM_API_ENDPOINT", DEFAULT_ENDPOINT)
#     if not os.getenv("LLM_API_KEY"):
#         print("警告：未设置 LLM_API_KEY 环境变量，回退到内置默认 key"
#               "（该 key 已进入仓库历史，建议吊销轮换并改用环境变量）")

#     agents = {
#         "bug": BugGenerationAgent(LLMConfig(api_key, endpoint, args.bug_model)),
#         "judge": ValidAgent(LLMConfig(api_key, endpoint, args.judge_model)),
#         "model_a": FilterTestGenerationAgent(
#             LLMConfig(api_key, endpoint, args.filter_model_a), args.suite_retries),
#         "model_b": FilterTestGenerationAgent(
#             LLMConfig(api_key, endpoint, args.filter_model_b), args.suite_retries),
#     }
#     print(f"bug 模型: {args.bug_model} | 等效判定: {args.judge_model} | "
#           f"过滤模型: {args.filter_model_a} / {args.filter_model_b}")

#     with open(args.data_path, "r", encoding="utf-8") as f:
#         data = json.load(f)
#     print(f"共 {len(data)} 个函数待处理")

#     delete_test_files_in_test_dirs(TESTBED)

#     final_results = []
#     stats = []
#     for idx, entry in enumerate(data):
#         name = entry.get("name", f"entry_{idx}")
#         print(f"\n===== [{idx + 1}/{len(data)}] {name} =====")
#         if not entry.get("code") or not entry.get("src_file"):
#             stats.append({"name": name, "status": "skipped_missing_fields"})
#             continue

#         accepted, accepted_data, traces = process_entry(entry, agents, args)
#         outcome = traces[-1]["outcome"] if traces else "no_attempts"

#         stats.append({"name": name, "status": "accepted" if accepted else outcome,
#                       "attempts": traces})

#         if accepted:
#             entry["buggy_code"] = [accepted_data["bug_code"]]
#             entry["tests"] = [accepted_data["suites"]["model_a"],
#                               accepted_data["suites"]["model_b"]]
#             entry["bug_summary"] = accepted_data["bug_summary"]
#             entry["flag"] = "dual_filter_pass"
#             entry["status"] = "accepted"
#             entry["filter_results"] = accepted_data["filter_results"]
#             # entry["escaped_original_suite"] = accepted_data["escaped_original_suite"]
#             # entry["original_failing_tests"] = accepted_data["original_failing_tests"]
#             entry["validation_result"] = accepted_data["validation"]
#             entry["filter_attempts"] = len(traces)
#             final_results.append(entry)
#             with open(args.results_path, "w", encoding="utf-8") as f:
#                 json.dump(final_results, f, ensure_ascii=False, indent=4)
#             try:
#                 os.makedirs(args.results_dir, exist_ok=True)
#                 shutil.copy(args.results_path, args.results_dir)
#             except OSError as e:
#                 print(f"复制结果文件失败: {e}")
#             print(f"已接受错误代码（尝试 {len(traces)} 次）:\n{accepted_data['bug_code'][:500]}")
#         else:
#             entry["flag"] = "not_accepted"
#             entry["status"] = outcome
#             entry["filter_attempts"] = len(traces)
#             print(f"未接受（{outcome}，尝试 {len(traces)} 次）")

#         with open(args.stats_path, "w", encoding="utf-8") as f:
#             json.dump(stats, f, ensure_ascii=False, indent=4)

#     print(f"\n完成：接受 {len(final_results)}/{len(data)} 条。"
#           f"明细见 {args.results_path} / {args.stats_path}")


# if __name__ == "__main__":
#     parser = argparse.ArgumentParser(
#         description="双大模型过滤的错误代码生成流程（Java/Maven）")
#     parser.add_argument("--data-path", type=str, required=True,
#                         help="输入 JSON 数据文件路径（需含 specification 字段）")
#     parser.add_argument("--bug-model", type=str, default="gpt-5.4-mini",
#                         help="bug 生成模型")
#     parser.add_argument("--judge-model", type=str, default="gpt-5.4-mini",
#                         help="等效判定模型")
#     parser.add_argument("--filter-model-a", type=str, default="gpt-5.4-mini",
#                         help="过滤模型 A（应与被评测模型不同厂商/代际）")
#     parser.add_argument("--filter-model-b", type=str, default="glm-5",
#                         help="过滤模型 B")
#     parser.add_argument("--attempts", type=int, default=5,
#                         help="每个函数的 bug 对抗尝试次数上限")
#     parser.add_argument("--suite-retries", type=int, default=2,
#                         help="每个 bug 尝试内测试套件的重新生成次数上限")
#     parser.add_argument("--results-path", type=str, default="/testbed/final_results.json")
#     parser.add_argument("--stats-path", type=str, default="/testbed/filter_stats.json")
#     parser.add_argument("--results-dir", type=str, default="/results")
#     main(parser.parse_args())
