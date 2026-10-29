"""
过滤阶段的测试生成器。

与评测协议严格同源：直接复用评测管线 gen_test/llm_gentests.py 的
TestCodeGenerator（specification 模式模板、temperature=0.2、max_tokens=16384、
max_K=3 重试），输入为"错误代码 + 规范"——与被评测模型看到的信息完全一致，
过滤准则即"在评测协议下该模型未检出此 bug"。

容器内由 eval_java_adver.py 将 gen_test/llm_gentests.py 挂载到 /testbed 下。
"""
import logging
import re

from openai import OpenAI

from llm_config import LLMConfig
from usage_tracker import usage_tracker

try:
    from test_gen import (
        TestGenerationAgent,
        expected_test_class_name,
        extract_java_code,
        java_compilation_context,
        call_with_production_tools,
        production_exploration_instructions,
        test_framework,
    )
except ImportError:  # 本地开发目录无 llm_gentests，容器内由挂载提供
    TestGenerationAgent = None
    expected_test_class_name = None
    extract_java_code = None
    java_compilation_context = None
    call_with_production_tools = None
    production_exploration_instructions = None
    test_framework = None

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "You are a professional test engineer specializing in writing high-quality unit test code."

class FilterTestGenerationAgent:
    def __init__(self, llm_config: LLMConfig, suite_retries: int = 2,
                 *, use_production_tools: bool = True):
        if TestGenerationAgent is None:
            raise ImportError(
                "test_gen.py 未找到：请将 gen_test/test_gen.py 挂载到 /testbed 下"
                "（eval_java_adver.py 已包含该挂载）"
            )
        self.llm_config = llm_config
        self.model_name = llm_config.MODEL_NAME
        self.suite_retries = suite_retries
        self.use_production_tools = use_production_tools
        self.current_entry = {}
        # specification 模式；JUnit 变体由每条数据的 test_framework 决定。
        self.generator = TestGenerationAgent(
            llm_config=llm_config, use_production_tools=use_production_tools)
        self.client = OpenAI(api_key=llm_config.API_KEY,
                             base_url=llm_config.API_ENDPOINT,
                             timeout=llm_config.REQUEST_TIMEOUT,
                             max_retries=0)

    @staticmethod
    def _function_info(entry, bug_code):
        """构造评测同款输入：generate_test_prompt 会取 buggy_code[-1] 放入 prompt。"""
        return {
            "name": entry.get("name", ""),
            "buggy_code": [bug_code],
            "code": entry.get("code", ""),
            "imports": entry.get("imports", entry.get("import", [])),
            "type": entry.get("type", "method"),
            "class_name": entry.get("class_name", None),
            "full_class_name": entry.get("full_class_name", ""),
            "class_constructor": entry.get("class_constructor", []),
            "class_fields": entry.get("class_fields", []),
            "specification": entry.get("specification", ""),
            "src_file": entry.get("src_file", ""),
            "test_file": entry.get("test_file", ""),
            "is_async": entry.get("is_async", False),
        }

    def generate_tests(self, entry, bug_code):
        """按评测协议为当前 bug 生成一套测试，失败返回空字符串。"""
        self.current_entry = entry
        try:
            tests = self.generator.init_test_prompt(
                bug_code, entry)
            # tests = self.generator.call_llm(prompt)
        except Exception as e:
            logger.error(f"[{self.model_name}] 测试生成失败: {e}")
            return ""
        # if tests and tests[0].strip():
        #     return tests[0].strip()
        return self.normalize_tests(tests, self._expected_class(entry))

    @staticmethod
    def _expected_class(entry):
        return expected_test_class_name(entry)

    def normalize_tests(self, tests, expected_class="", compiler_error=""):
        """Apply safe, deterministic fixes before asking the model to retry."""
        if not tests:
            return tests
        tests = extract_java_code(tests) if extract_java_code else tests.strip()
        entry = self.current_entry or {}
        expected_class = expected_class or self._expected_class(entry)
        # The model owns the complete Java compilation unit, including its
        # package declaration and all JUnit imports. Preserve that header so
        # compiler feedback can drive a normal agent-style correction.

        framework = test_framework(entry) if test_framework else "junit5"
        # Correct fully-qualified JUnit 4 references only for a Jupiter suite.
        if framework == "junit5":
            tests = tests.replace("org.junit.Test", "org.junit.jupiter.api.Test")
            tests = tests.replace("org.junit.Assert", "org.junit.jupiter.api.Assertions")

        # A frequent cross-version mistake is a JUnit 4 message-first
        # assertion in a JUnit 5 project.  The compiler's boolean/String
        # diagnostic identifies this case without risking changes to ordinary
        # string assertions.
        if framework == "junit5" and "boolean cannot be converted to" in compiler_error:
            tests = re.sub(
                r"assertEquals\(\s*(\"[^\"]*\")\s*,\s*(true|false)\s*,\s*([^,()]+)\s*\)",
                r"assertEquals(\2, \3, \1)", tests)
            tests = re.sub(
                r"assertTrue\(\s*(\"[^\"]*\")\s*,\s*(true|false|[A-Za-z_$][\w$]*)\s*\)",
                r"assertTrue(\2, \1)", tests)

        # Maven invokes the basename from entry['test_file']; a different
        # generated class name compiles but is invisible to -Dtest=...
        if expected_class:
            match = re.search(r"\bclass\s+([A-Za-z_$][\w$]*)", tests)
            if match and match.group(1) != expected_class:
                start, end = match.span(1)
                tests = tests[:start] + expected_class + tests[end:]
        return tests.strip()

    def _call(self, system, user, temperature=0.2):
        try:
            messages = [{"role": "system", "content": system},
                        {"role": "user", "content": user}]
            if self.use_production_tools:
                response_text = call_with_production_tools(
                    self.client, self.model_name, messages,
                    temperature=temperature, max_tokens=16384)
            else:
                response = self.client.chat.completions.create(
                    model=self.model_name, messages=messages,
                    temperature=temperature, max_tokens=16384)
                usage_tracker.record(self.model_name, response)
                response_text = response.choices[0].message.content or ""
            return extract_java_code(response_text)
        except Exception as e:
            logger.error(f"[{self.model_name}] LLM 调用失败: {e}")
            return ""

    def fix_compile(self, tests, error):
        """修复编译错误（复制自 test_gen.fix_test_prompt 的语义）。"""
        context = java_compilation_context(self.current_entry or {})
        prompt = f"""Required compilation context:
{context}

The test code below fails to compile with the following error:
        Tests:
        ```java
        {tests}
        ```

        Error:
        ```
        {error}
        ```

        Preserve the test's behavioral intent, target invocation, and expected
        outcomes. Only fix compilation or setup mechanics. Do not remove test
        cases, weaken assertions, change expected values to match the supplied
        implementation, disable/skip a test, or replace a test with a tautology.

        {production_exploration_instructions() if self.use_production_tools else 'No repository exploration tools are available. Use only the supplied context.'}

        Return the complete Java compilation unit, including its package
        declaration and all required explicit imports (including JUnit), with
        no Markdown fences. Use only the configured JUnit version.
        """
        print(f"修复编译错误 ({len(prompt)} chars)")
        return self.normalize_tests(
            self._call("You are a helpful assistant that fixes failing test code.", prompt))

    def repair_tests(self, tests, failure_output):
        """修复执行错误、编译错误或误报（failure_output 中说明具体问题）。"""
        context = java_compilation_context(self.current_entry or {})
        prompt = f"""Required compilation context:
{context}

The test code below has the following problems:
        Tests:
        ```java
        {tests}
        ```

        Error:
        ```
        {failure_output}
        ```

        Repair only test infrastructure, setup, or API-usage mistakes while
        preserving the test's behavioral intent, target invocation, and expected
        outcomes from the specification. Do not delete a failing case, weaken an
        assertion, change expected values merely to match the supplied code,
        disable/skip a test, use assumptions to avoid execution, catch-and-ignore
        failures, or replace a test with a tautology.

        {production_exploration_instructions() if self.use_production_tools else 'No repository exploration tools are available. Use only the supplied context.'}

        Return the complete Java compilation unit, including its package
        declaration and all required explicit imports (including JUnit), with
        no Markdown fences. Use only the configured JUnit version.
        """
        print(f"修复测试 ({len(prompt)} chars)")
        return self.normalize_tests(
            self._call("You are a helpful assistant that fixes failing test code.", prompt))
        
