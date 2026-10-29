import json
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from gen_specification import (
    TestCodeGenerator as SpecificationGenerator,
    _extract_function_records,
    system_prompt,
)


VALID_SPECIFICATION = """Functional Description: Does one thing.

Args:
value: int - Input value.

Returns: int - Result.

Preconditions:
- None

Postconditions:
- None

Invariants:
- None

Exception:
- None
"""


def make_generator_without_client():
    return object.__new__(SpecificationGenerator)


def test_system_prompt_defines_every_section_without_examples_or_placeholders():
    assert "### Example" not in system_prompt
    assert "Input:" not in system_prompt
    assert "<condition>" not in system_prompt
    assert "observable guarantees after normal completion" in system_prompt
    assert "proven across all relevant paths" in system_prompt
    assert "Follow catch flow" in system_prompt
    assert "non-nullable primitives" in system_prompt
    assert "supported input handled" in system_prompt
    assert "may still qualify as a precondition" in system_prompt
    assert "does not by itself prove" in system_prompt
    assert "Do not put input-output rules" in system_prompt
    assert "declaration alone is insufficient" in system_prompt
    assert "silently check" in system_prompt


def test_prompt_detects_language_and_includes_related_types():
    generator = make_generator_without_client()
    prompt = generator.generate_test_prompt({
        "name": "run",
        "src_file": "src/run.mjs",
        "code": "export function run(value) { return new Widget(value); }",
        "related_types": [{"file": "widget.js", "code": "class Widget {}"}],
    })

    assert "following JavaScript function or method" in prompt
    assert "class Widget {}" in prompt
    assert "widget.js" not in prompt


def test_call_llm_retries_and_returns_clean_string():
    generator = make_generator_without_client()
    generator.model = "fake-model"
    generator.max_output_tokens = 1000
    generator.max_retries = 2

    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("temporary failure")
        message = SimpleNamespace(content=f"```text\n{VALID_SPECIFICATION}\n```")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    generator.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    with patch("gen_specification.time.sleep") as sleep:
        result = generator.call_llm("prompt")

    assert result == VALID_SPECIFICATION.strip()
    assert isinstance(result, str)
    assert len(calls) == 2
    sleep.assert_called_once_with(1)


def test_call_llm_rejects_missing_sections_after_all_retries():
    generator = make_generator_without_client()
    generator.model = "fake-model"
    generator.max_output_tokens = 1000
    generator.max_retries = 2
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="Functional Description: incomplete"))]
    )
    generator.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response))
    )

    with patch("gen_specification.time.sleep"):
        with pytest.raises(RuntimeError, match="2 次尝试"):
            generator.call_llm("prompt")


def test_parallel_batch_preserves_input_order():
    class DelayedGenerator(SpecificationGenerator):
        def __init__(self):
            pass

        def generate_test_for_function(self, function_info):
            time.sleep(function_info["delay"])
            return {**function_info, "specification": VALID_SPECIFICATION}

    functions = [
        {"name": "first", "delay": 0.03},
        {"name": "second", "delay": 0.0},
        {"name": "third", "delay": 0.01},
    ]
    results = DelayedGenerator().generate_tests_for_functions_parallel_batch(
        functions, max_workers=3, batch_size=3, batch_delay=0
    )

    assert [item["name"] for item in results] == ["first", "second", "third"]


def test_atomic_save_does_not_overwrite_valid_file_on_serialization_error(tmp_path):
    generator = make_generator_without_client()
    output = tmp_path / "result.json"
    output.write_text('{"old": true}', encoding="utf-8")

    with pytest.raises(TypeError):
        generator.save_results({"bad": object()}, str(output))

    assert json.loads(output.read_text(encoding="utf-8")) == {"old": True}
    assert not list(tmp_path.glob(".result.json.*.tmp"))


def test_extract_function_records_supports_wrapper_and_validates_records():
    records, key = _extract_function_records({"metadata": {"v": 1}, "functions": [{"name": "f"}]})
    assert key == "functions"
    assert records == [{"name": "f"}]

    with pytest.raises(ValueError, match="记录必须全部"):
        _extract_function_records(["not-an-object"])
