"""One-off patch: add v3/v4/v5 bug-prompt versions to prompt_versions.py."""
import ast

p = 'scripts/prompt_versions.py'
s = open(p).read()

v3_code = '''

SYSTEM_V3 = """You are a talented Java programmer and experienced in realistic bug synthesis. The bugs you inject must be invisible in the source code: you never annotate, hint at, or explain the injected defect in any comment, string literal, log message, or identifier."""


def _v3_user(code, specification, buggy_code, test_info):
    middle = ""
    if buggy_code is not None:
        middle = f"""
We have already generated a buggy version of the code:
```java
{buggy_code}
```

And the bug is detected by existing tests:
{test_info}

Your task is to generate another **buggy version** of the code that keep the tests PASS.

## Goal
Create an buggy version of the code that:
- remains valid and compilable Java,
- different from the previous buggy version,
- pass the existing tests.
"""
    else:
        middle = """
Your task is to generate **buggy version** of the code.

## Goal
Create buggy version of the code that:
- remains valid and compilable Java
"""
    user_prompt = f"""
Below is the original Java code from a real project, followed by the natural-language specification that describes its intended behavior.

## Original code
```java
{code}
```

## Specification (intended behavior)
{_spec_text(specification)}
{middle}
## Critical constraint - No equivalent mutations
Do not produce code that is behaviorally identical to the original. Examples of forbidden "no-op" changes:
- renaming variables or reformatting,
- swapping loops or conditions that always evaluate to the same result,
- adding redundant null-checks or always-true/always-false conditions,
- any other change that leaves the observable output or side effects exactly the same in every possible execution.

## Stealth requirement - never annotate the bug
A test-generation model will read this code and try to locate the defect by inspection. The buggy code must look like ordinary production code:
- Keep every comment of the original code exactly as-is. Do NOT add, rewrite, or delete any comment.
- Do NOT write any comment that mentions, hints at, or explains the injected defect. Forbidden markers include: "BUG", "buggy", "fault", "defect", "mutant", "mutation", "FIXME", "XXX", "intentionally", "accidentally", "WRONG", "broken", "changed from original".
- Do NOT leak the defect into string literals, log messages, or exception texts (e.g. logger.warn("wrong page size"), throw new Exception("should be 100")).
- Do NOT use variable or method names that hint at the change (e.g. buggyValue, wrongSize, mutatedOffset).
- Keep naming, formatting, and style identical to the original code, so diffing the two versions reveals nothing beyond the defect itself.

## Note:
The buggy code must exhibit incorrect behavior in at least one scenario that the tests happen to miss.

## Output format

Return a JSON object exactly in the following format:

```json
{{
"bug_summary": "<2-3 sentences summary>",
"buggy_code": "<full buggy Java code>"
}}
```
"""
    return user_prompt


def init_bug_prompt_v3(code, specification):
    return SYSTEM_V3, _v3_user(code, specification, None, None)


def enhance_bug_prompt_v3(code, buggy_code, test_info, specification):
    return SYSTEM_V3, _v3_user(code, specification, buggy_code, test_info)

'''

v45_sections = '''

ADVERSARY_SIM_SECTION = """## Recommended procedure (do this privately; output only the JSON result)
1. Simulate the adversary first: draft, in your head, the 8-12 test cases a thorough test-generation model would write against this code and specification - covering the basic behaviors, every boundary case it lists (null / empty / single-element / duplicate / unknown / first-vs-last), the invalid-input and error-handling paths, and the configuration the specification mentions.
2. For each drafted test, note which code path and which inputs it exercises.
3. Choose a defect whose differing behavior lies OUTSIDE every drafted test: a path they do not reach, an input class they do not combine, a configuration interaction they do not enable, or a state/ordering condition they never set up.
4. Verify your choice: if you can write a one-line test using only the specification and default settings that would fail on your buggy code, pick a different defect."""

BUG_TYPES_SECTION = """## Bug types to consider
The bug should resemble a plausible human coding mistake, such as:
- an off-by-one or boundary error (exclusive vs inclusive bounds, first vs last element),
- a wrong branch condition or inverted guard,
- incorrect handling of empty/singleton/duplicate inputs,
- a wrong default value or parameter handling mistake,
- a subtle collection-processing mistake (wrong accumulation, wrong key, wrong ordering),
- a missing or extra state update (field not refreshed, cache not invalidated),
- incorrect exception handling or fallback behavior (wrong exception type, wrong fallback source),
- wrong precedence or ordering between two similar checks,
- a wrong constant or sentinel value,
- confusion between similar concepts (index vs position, count vs size, raw vs resolved value).

Pick the type and site that the specification and common tests are LEAST likely to cover."""


def init_bug_prompt_v4(code, specification):
    system, user = init_bug_prompt_v2(code, specification)
    user = user.replace("Your task is to generate a **buggy version** of this code.",
                        "Your task is to generate a **buggy version** of this code.\n\n" + ADVERSARY_SIM_SECTION)
    return system, user


def enhance_bug_prompt_v4(code, buggy_code, test_info, specification):
    system, user = enhance_bug_prompt_v2(code, buggy_code, test_info, specification)
    user = user.replace("Your task is to generate another **buggy version** of the code.",
                        "Your task is to generate another **buggy version** of the code.\n\n" + ADVERSARY_SIM_SECTION)
    return system, user


def init_bug_prompt_v5(code, specification):
    system, user = init_bug_prompt_v2(code, specification)
    user = user.replace("Your task is to generate a **buggy version** of this code.",
                        "Your task is to generate a **buggy version** of this code.\n\n" + BUG_TYPES_SECTION)
    return system, user


def enhance_bug_prompt_v5(code, buggy_code, test_info, specification):
    system, user = enhance_bug_prompt_v2(code, buggy_code, test_info, specification)
    user = user.replace("Your task is to generate another **buggy version** of the code.",
                        "Your task is to generate another **buggy version** of the code.\n\n" + BUG_TYPES_SECTION)
    return system, user

'''

anchor = 'def init_bug_prompt_v2(code, specification):'
s = s.replace(anchor, v3_code + '\n' + v45_sections + '\n' + anchor, 1)

s = s.replace('''VERSIONS = {"v1": (init_bug_prompt_v1, enhance_bug_prompt_v1),
            "v2": (init_bug_prompt_v2, enhance_bug_prompt_v2)}''',
'''VERSIONS = {"v1": (init_bug_prompt_v1, enhance_bug_prompt_v1),
            "v2": (init_bug_prompt_v2, enhance_bug_prompt_v2),
            "v3": (init_bug_prompt_v3, enhance_bug_prompt_v3),
            "v4": (init_bug_prompt_v4, enhance_bug_prompt_v4),
            "v5": (init_bug_prompt_v5, enhance_bug_prompt_v5)}''')

s = s.replace('DATA_PATH = "/data/home/cjy/SoftwareTestingBenchmark/databind_specification.json"',
              'DATA_PATH = os.environ.get("PROMPT_ITER_DATA",\n                          "/data/home/cjy/SoftwareTestingBenchmark/databind_specification.json")')
s = s.replace('import json\nimport sys', 'import json\nimport os\nimport sys')

open(p, 'w').write(s)
ast.parse(s)
print('v3/v4/v5 added; SYNTAX OK')
