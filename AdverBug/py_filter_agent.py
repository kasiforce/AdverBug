"""Python mutation and pytest-suite agents using the repository LLM contract."""
from __future__ import annotations

import ast
import json
import re
import time
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None

try:
    from .llm_config import LLMConfig
except ImportError:
    from llm_config import LLMConfig


SYSTEM_PROMPT = "You are a careful Python test engineer working with pytest. Return only the requested format."


def extract_code(text: str) -> str:
    text = (text or "").strip()
    match = re.search(r"```(?:python|py)?\s*\n?(.*?)```", text, re.IGNORECASE | re.DOTALL)
    return (match.group(1) if match else text).strip()


def parse_json_object(text: str):
    text = (text or "").strip()
    candidates = [text]
    fenced = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.IGNORECASE | re.DOTALL)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            value, _ = decoder.raw_decode(candidate)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    while start >= 0:
        try:
            value, _ = decoder.raw_decode(text[start:])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
        else:
            break
    return None


def syntax_check(code: str):
    try:
        compile(code, "<generated-python-test>", "exec")
        return True, ""
    except SyntaxError as exc:
        return False, f"SyntaxError: {exc}"


def function_context(entry: dict, original_code: str, buggy_code: str = "") -> str:
    specification = entry.get("specification") or ast.get_docstring(ast.parse(original_code), clean=False) if original_code else ""
    if isinstance(specification, list):
        specification = "\n\n".join(map(str, specification))
    return f"""Function name: {entry.get('name', '')}
Source file: {entry.get('src_file', '')}
Test file: {entry.get('test_file', '')}
Class: {entry.get('class_name') or 'standalone function'}
Async: {entry.get('is_async', False)}
Imports: {entry.get('imports', [])}

Original function:
```python
{original_code}
```

Mutated function (the candidate bug):
```python
{buggy_code}
```

Behavioral context:
{specification or 'Infer behavior from the original implementation and its docstring.'}
"""


class _LLMAgent:
    def __init__(self, config: LLMConfig, *, temperature=0.0, max_tokens=16384, retries=2):
        if OpenAI is None:
            raise RuntimeError("openai package is required")
        self.config = config
        self.client = OpenAI(api_key=config.API_KEY, base_url=config.API_ENDPOINT, max_retries=0)
        self.model = config.MODEL_NAME
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.retries = retries

    def call(self, messages):
        last = None
        for attempt in range(self.retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model, messages=messages,
                    temperature=self.temperature, max_tokens=self.max_tokens,
                )
                return (response.choices[0].message.content or "").strip()
            except Exception as exc:
                last = exc
                if attempt < self.retries:
                    time.sleep(2 ** attempt)
        raise last


class PythonBugAgent(_LLMAgent):
    def __init__(self, config, **kwargs):
        super().__init__(config, temperature=0.7, **kwargs)

    def generate(self, entry):
        code = entry["code"]
        prompt = f"""Create one plausible, non-equivalent semantic bug in this Python function. Keep valid Python syntax, indentation, decorators, names, comments, and strings unless a change is required. Do not add markers or explanations. Return JSON only with string fields bug_summary and buggy_code, where buggy_code is a complete replacement function.\n\n{function_context(entry, code)}"""
        value = parse_json_object(self.call([{"role": "system", "content": "You create subtle realistic Python defects."}, {"role": "user", "content": prompt}])) or {}
        return {"bug_summary": value.get("bug_summary", ""), "buggy_code": value.get("buggy_code", "")}

    def enhance(self, entry, previous, feedback):
        prompt = f"""Create a different plausible Python semantic bug that escapes the reported tests. Return JSON only with bug_summary and buggy_code. Preserve valid syntax and the function interface.\n\n{function_context(entry, entry['code'], previous)}\nFilter feedback:\n{feedback}"""
        value = parse_json_object(self.call([{"role": "system", "content": "You create subtle realistic Python defects."}, {"role": "user", "content": prompt}])) or {}
        return {"bug_summary": value.get("bug_summary", ""), "buggy_code": value.get("buggy_code", "")}


class PythonFilterAgent(_LLMAgent):
    def generate_tests(self, entry, original_code, buggy_code):
        prompt = f"""Generate a pytest suite for the function below. Return only Python code. Every test must be named test_*. Tests must pass against the original implementation and assert observable behavior; include normal, boundary, invalid-input, and relevant dependency/state cases. The suite should detect a real semantic difference if one is observable, but must not rely on implementation-private details.\n\n{function_context(entry, original_code, buggy_code)}"""
        return extract_code(self.call([{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]))

    def repair_tests(self, entry, original_code, buggy_code, tests, feedback):
        prompt = f"""Repair this pytest suite. Return only complete Python test code. It must collect and pass against the original implementation. Preserve useful coverage and correct imports.\n\n{function_context(entry, original_code, buggy_code)}\nCurrent tests:\n```python\n{tests}\n```\nPytest feedback:\n{feedback}"""
        return extract_code(self.call([{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]))


class PythonSemanticJudge(_LLMAgent):
    def __init__(self, config, **kwargs):
        super().__init__(config, temperature=0.3, max_tokens=4096, **kwargs)

    def validate(self, entry, original_code, buggy_code, tests):
        prompt = f"""Decide whether the mutated Python function has a real observable semantic difference from the original. Ignore cosmetic, unreachable, equivalent, or syntax-only changes. Return JSON only: {{\"is_valid_bug\": true/false, \"reason\": \"brief explanation\"}}.\n\n{function_context(entry, original_code, buggy_code)}\nCandidate tests:\n```python\n{tests}\n```"""
        value = parse_json_object(self.call([{"role": "system", "content": "You are a conservative semantic bug judge."}, {"role": "user", "content": prompt}]))
        return value if isinstance(value, dict) and isinstance(value.get("is_valid_bug"), bool) else {"is_valid_bug": False, "reason": "unparseable judge response"}
