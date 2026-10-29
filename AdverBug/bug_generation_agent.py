import os
import json
import openai
from openai import OpenAI
from llm_config import LLMConfig
from usage_tracker import usage_tracker
from test_gen import call_with_production_tools, production_exploration_instructions
import logging

logger = logging.getLogger(__name__)

MAX_BUG_TOOL_CALLS = 2

class BugGenerationAgent:
    def __init__(self, llm_config: LLMConfig):
        self.llm_config = llm_config
        self.client = OpenAI(api_key=self.llm_config.API_KEY,
                             base_url=self.llm_config.API_ENDPOINT,
                             timeout=self.llm_config.REQUEST_TIMEOUT,
                             max_retries=0)
        self.model = self.llm_config.MODEL_NAME

    # ---------------- 共享 prompt 片段（与实验脚本 prompt_versions.py 保持一致） ----------------

    ADVERSARY_SECTION = """## The adversary you must survive
After you submit the buggy code, an independent test-generation model will receive your buggy code together with the same specification, and will write a unit test suite in the project's standard test framework ({framework}) designed so that at least one test exposes an incorrect implementation. It systematically probes:
- basic valid inputs and their expected outputs,
- boundary conditions: null / empty / single-element / duplicate / unknown / first-vs-last values,
- invalid inputs and error handling (wrong types, malformed input, missing required values),
- interactions with surrounding dependencies and configuration.

Consequences for where you place the defect:
- Avoid directly negating explicitly enumerated examples or simple main-path postconditions, and avoid trivial common boundary cases.
- Prefer reachable behavior whose intended result is derivable from the specification and surrounding code but requires non-trivial reasoning or non-default settings.
- Do not rely on unspecified behavior. The defect must still violate a meaningful, reachable intended behavior.
- At the defect site, the buggy behavior should still look like plausible production code — a careful reader would need non-trivial reasoning or non-default settings to tell it apart from the original."""

    DEFECT_FORM_SECTION = """## Defect form
Preferred (high stealth):
- Wrong identifier: using a type-compatible variable that belongs elsewhere (e.g., using a variable from site B where one from site A is expected),
- Precedence error in the interaction of two or more configuration flags/features/settings,
- Choosing the wrong source in a fallback chain (where multiple sources could supply the same value),
- Choosing a subtly wrong API when two methods differ only in edge cases.

Acceptable (medium stealth):
- Swapping the order of two if blocks that both return or both mutate state,
- Reordering two branches of a fallback chain,
- Coordinated control-flow or data-flow changes whose incorrect effect appears only when two or more inputs, configuration sources, state transitions, or fallback branches interact.

Forbidden (low stealth — the candidate will be rejected):
- An isolated comparison-operator replacement such as >= → >, <= → <, == → !=, or changing only one guard from stronger to weaker,
- A single-point negation (x → !x) or isolated boolean flip,
- Changing only one numeric, character, enum, or string literal,
- Any defect whose entire semantic change can be described as a one-token or one-character substitution, insertion, or deletion,
- Padding one of these trivial mutations with unrelated edits, formatting changes, or refactoring to make the diff look larger.

The defect must causally depend on at least two distinct semantic elements. You may change one or multiple related statements, but every changed statement must be necessary for that single interaction-based defect. Merely placing a trivial operator or literal mutation in a rarely tested branch does not make it acceptable.

Do NOT broadly restructure the method. You may add, remove, or modify multiple statements when those changes are jointly necessary for one coherent defect scenario. Do not make unrelated edits, refactors, or cosmetic changes, and do not touch comments, formatting, or naming."""

    NOEQUIV_SECTION = """## Critical constraint — No equivalent mutations
The candidate must change at least one observable result, side effect, or thrown
exception for a reachable input or configuration. Renaming, formatting,
refactoring, redundant checks, or statement reordering with no observable effect
is not a bug."""

    NOVELTY_SECTION = """## Semantic novelty relative to the previous candidate
When a previous buggy version is supplied, the new defect must change all of
these: the defect category or causal mechanism,
the triggering input/state combination, the affected data flow or observable
behavior, and the defect location. Do not mutate the same statement, expression,
or data structure through an equivalent change.

Changing only a summary, variable name, literal spelling, branch order, or the
description of the same precedence, flush, guard, or null-handling mistake is
still the same defect. Choose a different mechanism and state its new trigger
and observable consequence in the bug summary."""

    STEALTH_SECTION = """## Stealth requirement — never annotate the bug
A test-generation model will read this code and try to locate the defect by inspection. The buggy code must look like ordinary production code:
- Keep every comment of the original code exactly as-is. Do NOT add, rewrite, or delete any comment.
- Do NOT write any comment that mentions, hints at, or explains the injected defect. Forbidden markers include: "BUG", "buggy", "fault", "defect", "mutant", "mutation", "FIXME", "XXX", "intentionally", "accidentally", "WRONG", "broken", "changed from original".
- Do NOT leak the defect into string literals, log messages, or exception texts (e.g. logger.warn("wrong page size"), throw new Exception("should be 100")).
- Do NOT use variable or method names that hint at the change (e.g. buggyValue, wrongSize, mutatedOffset).
- Keep naming, formatting, and style identical to the original code, so diffing the two versions reveals nothing beyond the defect itself."""

    OUTPUT_SECTION = """## Output format

Return one JSON object and no Markdown fences, prose, or extra keys:

{
"bug_summary": "<2-3 sentences summary>",
"buggy_code": "<full buggy code, same unit as the original>"
}
"""

    # ---------------- 每语言配置（shared strategy sections + per-language flavor） ----------------

    LANGUAGE_PROFILES = {
        "java": {
            "label": "Java",
            "fence": "java",
            "framework": "JUnit",
            "validity": "remains valid, compilable Java, with the same method signature and unit boundaries",
        },
        "javascript": {
            "label": "JavaScript",
            "fence": "javascript",
            "framework": "Jest",
            "validity": "remains valid JavaScript that parses and runs under the project's test runner, with the same function signature and unit boundaries",
        },
        "python": {
            "label": "Python",
            "fence": "python",
            "framework": "pytest",
            "validity": "remains valid Python that parses and imports cleanly, with the same function signature and unit boundaries",
        },
    }

    @classmethod
    def _profile(cls, language):
        key = (language or "java").strip().lower()
        if key not in cls.LANGUAGE_PROFILES:
            key = "java"
        return cls.LANGUAGE_PROFILES[key]

    @staticmethod
    def _spec_text(specification):
        """specification 兼容 str / list；为空时返回占位说明。"""
        if not specification:
            return "(No specification was provided. Derive the intended behavior from the code itself, and be extra conservative: keep the defect in code paths whose contract is not evident from names or structure.)"
        if isinstance(specification, list):
            return "\n\n".join(str(x) for x in specification)
        return str(specification)

    @staticmethod
    def _clip(text, limit):
        text = str(text or "")
        return text if len(text) <= limit else text[:limit] + "\n... [truncated]"

    @classmethod
    def _summary_history_text(cls, summaries):
        """Format all earlier defect summaries for cross-attempt deduplication."""
        items = [str(item).strip() for item in (summaries or []) if str(item).strip()]
        if not items:
            return "(No earlier defect summaries.)"
        return cls._clip("\n".join(
            f"{index}. {summary}" for index, summary in enumerate(items, 1)), 6000)

    @classmethod
    def _context_text(cls, context):
        """Build compact source context without preselecting callee implementations."""
        if not isinstance(context, dict):
            return "(No additional class context was supplied.)"

        def as_block(value):
            if isinstance(value, list):
                return "\n".join(str(item) for item in value if item)
            return str(value or "")

        sections = [
            f"Class: {context.get('full_class_name') or context.get('class_name') or '(unknown)'}",
            f"Source file: {context.get('src_file') or '(unknown)'}",
        ]
        constructors = as_block(context.get("class_constructor"))
        fields = as_block(context.get("class_fields"))
        if constructors:
            sections.append(f"Constructors:\n{constructors}")
        if fields:
            sections.append(f"Relevant fields:\n{fields}")
        related_type_blocks = []
        for related_type in context.get("related_types") or []:
            if not isinstance(related_type, dict):
                text = str(related_type or "").strip()
                if text:
                    related_type_blocks.append(text)
                continue
            label = (related_type.get("qualified_name") or related_type.get("name")
                     or "(unknown type)")
            block = [f"Type: {label}"]
            if related_type.get("file"):
                block.append(f"Source file: {related_type['file']}")
            if related_type.get("relation_evidence"):
                block.append(f"Relation: {related_type['relation_evidence']}")
            if related_type.get("code"):
                block.append(f"Declaration:\n{related_type['code']}")
            related_type_blocks.append("\n".join(block))
        if related_type_blocks:
            sections.append("Related types:\n" + "\n\n".join(related_type_blocks))
        return cls._clip("\n\n".join(sections), 7000)

    def init_bug_prompt(self, code, specification=None, language="java", context=None):
        prof = self._profile(language)
        system_prompt = f"""You are a talented {prof["label"]} programmer and experienced in realistic bug synthesis. The bugs you inject must be invisible in the source code: you never annotate, hint at, or explain the injected defect in any comment, string literal, log message, or identifier."""

        user_prompt = f"""
Below is the original {prof["label"]} code of a function from a real project, followed by the natural-language specification that describes its intended behavior.

## Original code
```{prof["fence"]}
{code}
```

## Specification (intended behavior)
{self._spec_text(specification)}

## Source-derived class context
{self._context_text(context)}

Use this context only to understand reachable state and available symbols. Output a
drop-in replacement for the supplied code unit only; do not modify other methods,
classes, imports, annotations, modifiers, generic parameters, or its signature.

Your task is to generate a **buggy version** of this code.

{self.ADVERSARY_SECTION.format(framework=prof["framework"])}

## Goal
Create a buggy version of the code that:
- {prof["validity"]},
- maximizes the likelihood that the adversary's generated suite will miss at least one real defect scenario,

{self.DEFECT_FORM_SECTION}

{self.NOEQUIV_SECTION}

{self.STEALTH_SECTION}

{self.OUTPUT_SECTION}
"""
        return self._request_bug(system_prompt, user_prompt)

    def enhance_bug_prompt(self, code, buggy_code, test_info, specification=None,
                           language="java", context=None, test_source="",
                           previous_summaries=None):
        prof = self._profile(language)
        system_prompt = f"""You are a talented {prof["label"]} programmer and experienced in realistic bug synthesis. The bugs you inject must be invisible in the source code: you never annotate, hint at, or explain the injected defect in any comment, string literal, log message, or identifier."""

        user_prompt = f"""
Below is the original {prof["label"]} code of a function from a real project, followed by the natural-language specification that describes its intended behavior.

## Original code
```{prof["fence"]}
{code}
```

## Specification (intended behavior)
{self._spec_text(specification)}

## Source-derived class context
{self._context_text(context)}

## Earlier defect summaries from this function
{self._summary_history_text(previous_summaries)}

Do not repeat any earlier candidate's causal mechanism, trigger, affected data
flow, observable consequence, or defect location. This history covers all prior
attempts, not only the immediately preceding candidate.

We have already generated a buggy version of the code:
```{prof["fence"]}
{buggy_code}
```

The previous mutation was detected by a generated filter suite. Its execution
feedback is:
{test_info}

## Generated filter test source
```{prof["fence"]}
{self._clip(test_source, 14000) if test_source else '(test source unavailable)'}
```

Your task is to generate another **buggy version** of the code.

## First, diagnose the detection
Use the test source and execution feedback to infer why the filter suite detected
the previous mutation. Do not assume a reason when the evidence is insufficient.
Choose a defect site AND mechanism of a different class:
- keep away from the code paths and input classes the detected tests exercise,
- prefer places where correctness depends on interactions of configuration flags, fallback/default chains, raw vs resolved values, or order/state-dependent behavior that the specification does not explicitly pin down,
- apply the semantic-novelty rules below.

{self.ADVERSARY_SECTION.format(framework=prof["framework"])}

{self.NOVELTY_SECTION}

## Goal
Create a buggy version of the code that:
- {prof["validity"]},
- maximizes the likelihood that the adversary's next generated suite will miss at least one real defect scenario,

{self.DEFECT_FORM_SECTION}

{self.NOEQUIV_SECTION}

{self.STEALTH_SECTION}

{self.OUTPUT_SECTION}
"""
        return self._request_bug(system_prompt, user_prompt)

    def retry_bug_prompt(self, code, previous_buggy_code, rejection_reason,
                         specification=None, language="java", context=None,
                         previous_summaries=None):
        """Regenerate after a non-detection rejection without inventing test feedback."""
        prof = self._profile(language)
        system_prompt = f"""You are a talented {prof["label"]} programmer and experienced in realistic bug synthesis. The bugs you inject must be invisible in the source code: you never annotate, hint at, or explain the injected defect in any comment, string literal, log message, or identifier."""
        user_prompt = f"""
Below is the original {prof["label"]} code of a function from a real project.

## Original code
```{prof["fence"]}
{code}
```

## Specification (intended behavior)
{self._spec_text(specification)}

## Source-derived class context
{self._context_text(context)}

## Earlier defect summaries from this function
{self._summary_history_text(previous_summaries)}

Do not repeat any earlier candidate's causal mechanism, trigger, affected data
flow, observable consequence, or defect location. This history covers all prior
attempts, not only the immediately preceding candidate.

A previous candidate was rejected for the following reason. This does NOT mean a
test detected it; do not invent test coverage or test feedback.

## Previous candidate
```{prof["fence"]}
{previous_buggy_code or '(no usable previous candidate)'}
```

## Rejection feedback
{self._clip(rejection_reason, 7000) or '(none)'}

Generate a fresh buggy version and apply the semantic-novelty rules below.
It must be a drop-in replacement for the supplied code unit only; do not modify
other methods, classes, imports, annotations, modifiers, generic parameters, or
its signature.

{self.ADVERSARY_SECTION.format(framework=prof["framework"])}

{self.NOVELTY_SECTION}

## Goal
Create a buggy version that:
- {prof["validity"]},
- introduces a meaningful, reachable semantic difference,
- maximizes the likelihood that a generated filter suite will miss at least one real defect scenario.

{self.DEFECT_FORM_SECTION}

{self.NOEQUIV_SECTION}

{self.STEALTH_SECTION}

{self.OUTPUT_SECTION}
"""
        return self._request_bug(system_prompt, user_prompt)

    def _request_bug(self, system_prompt, user_prompt):
        message = [{"role": "system", "content": system_prompt},
                   {"role": "user", "content": user_prompt}
                   ]
        try:
            message[1]["content"] += "\n\n" + production_exploration_instructions(
                MAX_BUG_TOOL_CALLS, "required buggy-code JSON object")
            content = call_with_production_tools(
                self.client, self.model, message, temperature=0.5,
                max_tokens=16384, max_tool_calls=MAX_BUG_TOOL_CALLS).strip()
            parsed = self._parse_bug_response(content)
            if parsed is None:
                raise ValueError("response was not a valid bug JSON object")
            print(f"Generated buggy-code candidate ({len(parsed['buggy_code'])} chars)")
            return parsed
        except Exception as e:
            logger.error(f"Error calling LLM for bug generation: {e}")
            return None  # Return None on error; caller treats as generation failure

    @staticmethod
    def _parse_bug_response(content):
        """Extract a JSON object even when an endpoint ignores JSON mode fences."""
        if not isinstance(content, str):
            return None
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
        start = cleaned.find("{")
        if start < 0:
            return None
        try:
            parsed, _ = json.JSONDecoder().raw_decode(cleaned[start:])
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        if not isinstance(parsed.get("buggy_code"), str):
            return None
        if not isinstance(parsed.get("bug_summary", ""), str):
            return None
        return parsed

    def debug(self):
        system_prompt = f"""You are a talented {prof["label"]} programmer and experienced in realistic bug synthesis. The bugs you inject must be invisible in the source code: you never annotate, hint at, or explain the injected defect in any comment, string literal, log message, or identifier."""

        user_prompt = """
    Below is the original Java code from a real project:
    ```java
    protected List<Queue<String>> makeColumnQueues(final List<String> columnData, final List<TextStyle> styles) {\n        final List<Queue<String>> result = new ArrayList<>();\n        for (int i = 0; i < columnData.size(); i++) {\n            result.add(makeColumnQueue(columnData.get(i), styles.get(i)));\n        }\n        return result;\n    }
    ````

    We have already generated a buggy version of the code:
    ```java
    protected List<Queue<String>> makeColumnQueues(final List<String> columnData, final List<TextStyle> styles) {\n    final List<Queue<String>> result = new ArrayList<>();\n    for (int i = 0; i + 1 < columnData.size(); i++) {\n        result.add(makeColumnQueue(columnData.get(i), styles.get(i)));\n    }\n    return result;\n}
    ```

    And the bug is detected by existing tests:
    ```java
    package org.apache.commons.cli.help;\n\nimport org.junit.Test;\nimport static org.junit.Assert.*;\nimport java.util.*;\n\npublic class MakeColumnQueuesTests {\n\n    public static class TestableTextHelpAppendable extends TextHelpAppendable {\n        public List<String> capturedData = new ArrayList<>();\n        public List<TextStyle> capturedStyles = new ArrayList<>();\n\n        public TestableTextHelpAppendable(final Appendable output) {\n            super(output);\n        }\n\n        protected Queue<String> makeColumnQueue(final String data, final TextStyle style) {\n            capturedData.add(data);\n            capturedStyles.add(style);\n            Queue<String> q = new LinkedList<>();\n            q.add(\"Q:\" + data);\n            return q;\n        }\n    }\n\n    @Test\n    public void testMakeColumnQueues_basic() {\n        TestableTextHelpAppendable helper = new TestableTextHelpAppendable(new StringBuilder());\n\n        List<String> columnData = Arrays.asList(\"one\", \"two\", \"three\");\n        List<TextStyle> styles = Arrays.asList((TextStyle) null, (TextStyle) null, (TextStyle) null);\n\n        List<Queue<String>> result = helper.makeColumnQueues(columnData, styles);\n\n        assertEquals(columnData.size(), result.size());\n        assertEquals(columnData.size(), helper.capturedData.size());\n\n        assertEquals(\"one\", helper.capturedData.get(0));\n        assertNull(helper.capturedStyles.get(0));\n\n        assertEquals(\"Q:one\", result.get(0).peek());\n\n        assertEquals(\"two\", helper.capturedData.get(1));\n        assertNull(helper.capturedStyles.get(1));\n        assertEquals(\"Q:two\", result.get(1).peek());\n\n        assertEquals(\"three\", helper.capturedData.get(2));\n        assertNull(helper.capturedStyles.get(2));\n        assertEquals(\"Q:three\", result.get(2).peek());\n    }\n\n    @Test\n    public void testMakeColumnQueues_empty() {\n        TestableTextHelpAppendable helper = new TestableTextHelpAppendable(new StringBuilder());\n\n        List<String> columnData = Collections.emptyList();\n        List<TextStyle> styles = Collections.emptyList();\n\n        List<Queue<String>> result = helper.makeColumnQueues(columnData, styles);\n\n        assertEquals(0, result.size());\n        assertTrue(helper.capturedData.isEmpty());\n        assertTrue(helper.capturedStyles.isEmpty());\n    }\n}
    <testcase name="testMakeColumnQueues_basic" classname="org.apache.commons.cli.help.MakeColumnQueuesTests" time="0.002">
    <error type="java.lang.NullPointerException"><![CDATA[java.lang.NullPointerException
	at org.apache.commons.cli.help.TextHelpAppendable.makeColumnQueue(TextHelpAppendable.java:312)
	at org.apache.commons.cli.help.TextHelpAppendable.makeColumnQueues(TextHelpAppendable.java:341)
	at org.apache.commons.cli.help.MakeColumnQueuesTests.testMakeColumnQueues_basic(MakeColumnQueuesTests.java:35)
	at java.lang.reflect.Method.invoke(Method.java:498)
]]></error>

    Your task is to generate another **buggy version** of the code that keep the tests PASS.

    ## Goal
    Create an buggy version of the code that:
    - remains valid and compilable Java,
    - pass the existing tests.

    ## Critical constraint – No equivalent mutations
    Do not produce code that is behaviorally identical to the original. Examples of forbidden "no-op" changes:
    - renaming variables or reformatting,
    - swapping loops or conditions that always evaluate to the same result,
    - adding redundant null‑checks or always‑true/always‑false conditions,
    - any other change that leaves the observable output or side effects exactly the same in every possible execution.
    The buggy code must exhibit incorrect behavior in at least one scenario that the tests happen to miss.

    ## Bug types to consider
    The bug should resemble a plausible human coding mistake, such as: 
    - an off-by-one or boundary error, 
    - a wrong branch condition, 
    - incorrect handling of empty/singleton inputs, 
    - a wrong default value or parameter handling mistake, 
    - a subtle collection-processing mistake, 
    - a missing/incorrect state update, 
    - incorrect exception handling or fallback behavior.


    ## Output format

    Return a JSON object exactly in the following format:

    ```json
    {
    "bug_type": "<bug category>",
    "bug_summary": "<2-3 sentences summary>",
    "buggy_code": "<full buggy code, same unit as the original>"
    }
    ```
    """
        message = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                    ]
        # return message
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=message,
                temperature=0.2,
                max_tokens=16384
            )
            usage_tracker.record(self.model, response)
            buggy_code = response.choices[0].message.content.strip()
            # Ensure we only get JSON object if LLM adds markdown
            if buggy_code.startswith("```json") and buggy_code.endswith("```"):
                buggy_code = buggy_code[len("```json"):-len("```")].strip()
                buggy_code = json.loads(buggy_code)
                print(f"Enhanced buggy code: {buggy_code}")
            return buggy_code
        except Exception as e:
            logger.error(f"Error calling LLM for bug generation: {e}")
            return "" # Return empty on error

    def _call(self, system, user, temperature=0.2):
        try:
            content = call_with_production_tools(
                self.client, self.model,
                [{"role": "system", "content": system},
                 {"role": "user", "content": user + "\n\n" + production_exploration_instructions(
                     MAX_BUG_TOOL_CALLS, "corrected Java code")}],
                temperature=temperature, max_tokens=16384,
                max_tool_calls=MAX_BUG_TOOL_CALLS).strip()
            return content.split("```java")[-1].split("```")[0].strip()
        except Exception as e:
            logger.error(f"Error calling LLM: {e}")
            return ""

    def fix_bug_prompt(self, bug_code: str, error: str) -> str:
        """修复编译错误，保持注入的逻辑与注释不变。"""
        prompt = f"""The code below fails to compile with the following error:
        Code:
        ```java
        {bug_code}
        ```

        Error:
        ```
        {error}
        ```

        Please provide a corrected version of the code that compiles.

        Preserve the intended semantic mutation. Make only the smallest
        compilation-only changes necessary; do not revert the behavioral
        difference or introduce another independent behavioral edit. Preserve
        comments, string literals, log messages, and identifiers unless changing
        one is strictly necessary to resolve the compilation error.
        ```java
        <corrected code>
        ```
        """
        return self._call(
            "You are a helpful assistant that fixes compilation errors in Java code while keeping its logic and comments unchanged.",
            prompt)



if __name__ == "__main__":
    # Example usage (will require actual API key and endpoint)
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("LLM_API_KEY is required")
    llm_config_instance = LLMConfig(api_key=api_key,
                                    api_endpoint=os.getenv("LLM_API_ENDPOINT", "https://api.agicto.cn/v1"),
                                    model_name=os.getenv("LLM_MODEL_NAME", "gpt-5.4-mini"))

    agent = BugGenerationAgent(llm_config=llm_config_instance)
    print(agent.debug())
