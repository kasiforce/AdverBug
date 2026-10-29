"""Test-generation prompt variants for the exp2 matrix.

T0: the protocol prompt, rendered EXACTLY by AdverBug/test_gen.py (via prompts_bridge).
T1: hunter variant - actively probe for defects, non-default configs, unusual
    combinations/orderings/repeats.
T2: spec-strict variant - expected values derived EXCLUSIVELY from the
    specification; no speculative assertions (targets false-positive suites).

All variants keep the same mechanical skeleton (function code, specification,
method context, test framework, output format) so only the strategy differs.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from prompts_bridge import render_init_test, load_entries  # noqa: E402

SYSTEM = "You are a professional test engineer specializing in writing high-quality unit test code"

T1_EXTRA_TASKS = """2. Assume the implementation under test may contain subtle defects: your tests should actively try to expose behavioral deviations, not only confirm that correct behavior works.
3. Design test cases that cover:
- Basic functionality with valid inputs and expected outputs.
- Boundary conditions and edge cases, including extreme values just outside the ordinary.
- Invalid inputs and error handling.
- Potential issues with dependency interactions.
- Non-default configuration paths and interactions between configuration and input.
- Unusual input combinations, orderings, repeated calls, and interleavings."""

T1_EXTRA_GOAL = """- Prefer tests that maximize behavioral differentiation: a test that asserts a specific, easily-predicted outcome is worth less than one that pins down a rarely-exercised path.
- A correct implementation should pass all tests."""

T2_EXTRA_TASKS = """2. Derive every expected value EXCLUSIVELY from the specification:
- If the specification determines a behavior, assert that behavior precisely.
- If the specification does NOT determine a behavior, do NOT assert a specific expected value; either skip that scenario or assert only the part the specification states.
3. Design test cases that cover the behaviors the specification describes:
- The main functional behaviors and their documented outcomes.
- Boundary and error behaviors that the specification explicitly states.
- Interactions the specification explicitly describes."""

T2_EXTRA_GOAL = """- Prefer fewer, well-justified assertions over many speculative ones: a test whose expectation you cannot justify from the specification is a liability.
- A correct implementation should pass all tests."""


def _user_prompt(entry, buggy_code, extra_tasks, extra_goal):
    function_name = entry['name']
    function_code = entry['code']
    class_name = None
    class_info = {}
    if entry['type'] == "method":
        class_name = entry.get('class_name')
        class_info['class_name'] = class_name
        if entry.get('class_constructor'):
            class_info['class_constructor'] = entry['class_constructor']
        if entry.get('class_fields'):
            class_info['class_fields'] = entry['class_fields']

    imports = entry.get('imports', [])
    specification = entry['specification']
    file_path = entry['src_file']
    test_path = entry['test_file']

    return f"""
Your job is to output corresponding test code that invokes the code under test.
You are given the following information:
- Function code
- Specification

Your tasks:
1. Infer the **intended behavior** from the specification.
{extra_tasks}
4. Write executable test code using Java 17 and JUnit 4.
5. The test code should be written into {test_path}. Please make sure the imports are correct.
6. Ensure tests are designed to differentiate between correct and incorrect implementations:
- At least one test should be able to expose an incorrect implementation if the code were incorrect.
{extra_goal}

## Function ({function_name}):
```java
{buggy_code}
```

## Specification:
{specification}

## Method Context:
- Src file: {file_path}
- Imports: {imports}
- Class: {class_info if class_name else 'Standalone function'}
- Is async: {entry.get('is_async', False)}


### Output Format ###:
Return ONLY code without explanations, non-code text, or markdown formatting.
```java
<test code>
```
"""


def render_variant(variant, entry, buggy_code):
    """Returns (system, user) messages for the chosen variant."""
    if variant == "T0":
        return render_init_test(entry, buggy_code)
    if variant == "T1":
        return SYSTEM, _user_prompt(entry, buggy_code, T1_EXTRA_TASKS, T1_EXTRA_GOAL)
    if variant == "T2":
        return SYSTEM, _user_prompt(entry, buggy_code, T2_EXTRA_TASKS, T2_EXTRA_GOAL)
    raise ValueError(variant)


VARIANTS = ("T0", "T1", "T2")


if __name__ == "__main__":
    import json
    data = os.environ.get("PROMPT_ITER_DATA",
                          "/data/home/cjy/SoftwareTestingBenchmark/AdverBug/prompt_iter/databind_specification_10.json")
    idx = int(sys.argv[1])
    buggy = open(sys.argv[2]).read().strip()
    variant = sys.argv[3]
    with open(data) as f:
        entries = json.load(f)
    system, user = render_variant(variant, entries[idx], buggy)
    print(len(system), len(user))
