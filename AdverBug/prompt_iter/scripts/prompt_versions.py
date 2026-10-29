"""Candidate bug-generation prompt versions for the iteration experiment.

v1: adds specification context + adversary modeling + defect placement strategy
    + defect-form guidance. Mirrors the JSON output contract of the current code.

CLI:
  python prompt_versions.py dump <version> <out.json>
"""
import json
import os
import sys

DATA_PATH = os.environ.get("PROMPT_ITER_DATA",
                          "/data/home/cjy/SoftwareTestingBenchmark/databind_specification.json")

SYSTEM_V1 = """You are a talented Java programmer and experienced in realistic bug synthesis. The bugs you inject must be invisible in the source code: you never annotate, hint at, or explain the injected defect in any comment, string literal, log message, or identifier."""


def _spec_text(specification):
    if isinstance(specification, list):
        return "\n\n".join(str(s) for s in specification)
    return str(specification)


STEALTH_SECTION = """## Stealth requirement — never annotate the bug
A test-generation model will read this code and try to locate the defect by inspection. The buggy code must look like ordinary production code:
- Keep every comment of the original code exactly as-is. Do NOT add, rewrite, or delete any comment.
- Do NOT write any comment that mentions, hints at, or explains the injected defect. Forbidden markers include: "BUG", "buggy", "fault", "defect", "mutant", "mutation", "FIXME", "XXX", "intentionally", "accidentally", "WRONG", "broken", "changed from original".
- Do NOT leak the defect into string literals, log messages, or exception texts (e.g. logger.warn("wrong page size"), throw new Exception("should be 100")).
- Do NOT use variable or method names that hint at the change (e.g. buggyValue, wrongSize, mutatedOffset).
- Keep naming, formatting, and style identical to the original code, so diffing the two versions reveals nothing beyond the defect itself."""

NOEQUIV_SECTION = """## Critical constraint — No equivalent mutations
Do not produce code that is behaviorally identical to the original. Examples of forbidden “no-op” changes:
- renaming variables or reformatting,
- swapping loops or conditions that always evaluate to the same result,
- adding redundant null‑checks or always‑true/always‑false conditions,
- any other change that leaves the observable output or side effects exactly the same in every possible execution.
Also forbidden (these are refactors, not bugs): inlining or extracting a helper method, hoisting or caching a variable, or reordering statements, when the resulting observable behavior is unchanged on every input. The single edit you make MUST change at least one observable outcome — a returned/stored value, a thrown exception and its message, or mutated state — for at least one reachable input or configuration."""

NOEQUIV_SECTION_V1 = NOEQUIV_SECTION.split("Also forbidden")[0].rstrip()

ADVERSARY_SECTION = """## The adversary you must survive
After you submit the buggy code, an independent test-generation model will receive your buggy code together with the same specification, and will write a JUnit test suite designed so that at least one test exposes an incorrect implementation. It systematically probes:
- basic valid inputs and their expected outputs,
- boundary conditions: null / empty / single-element / duplicate / unknown / first-vs-last values,
- invalid inputs and error handling (wrong types, malformed input, missing required values),
- interactions with surrounding dependencies and configuration.

Consequences for where you place the defect:
- A defect in any behavior the specification explicitly pins down, or in any of the common boundary cases above, WILL very likely be detected. Never place the defect there.
- Place the defect where behavior is underdetermined or expensive to pin down: interactions of two or more configuration flags/features/settings; rarely-used combinations of input kind and internal state; fallback or default-value chains where several sources could supply the same value; order-dependent, idempotency-sensitive, or repeat-call paths; behavior the specification mentions only vaguely or not at all and that must be derived from the code structure itself.
- At the defect site, the buggy behavior should still look like plausible production code — a careful reader would need non-trivial reasoning or non-default settings to tell it apart from the original."""


DEFECT_FORM_SECTION = """## Defect form
Prefer a minimal, realistic human mistake inside existing statements, for example:
- the wrong identifier: a raw/staged value used where a fully-processed or resolved value is expected (or vice versa),
- a comparison operator or guard that is slightly too strong / too weak / inverted,
- the wrong precedence or ordering between two similar checks,
- the wrong constant, wrong default, or wrong source chosen in a fallback chain,
- a subtly wrong API choice where two methods differ only in an edge case.
Do NOT restructure the method, do NOT add or remove statements beyond what the single edit requires, and do NOT touch comments, formatting, or naming."""


def init_bug_prompt_v1(code, specification):
    user_prompt = f"""
Below is the original Java code from a real project, followed by the natural-language specification that describes its intended behavior.

## Original code
```java
{code}
```

## Specification (intended behavior)
{_spec_text(specification)}

Your task is to generate a **buggy version** of this code.

{ADVERSARY_SECTION}

## Goal
Create a buggy version of the code that:
- remains valid and compilable Java, with the same method signature and unit boundaries,
- exhibits incorrect behavior in at least one scenario that the adversary's test suite will miss,
- differs from the original in one small, plausible edit.

{DEFECT_FORM_SECTION}

{NOEQUIV_SECTION_V1}

{STEALTH_SECTION}

## Output format

Return a JSON object exactly in the following format:

```json
{{
"bug_summary": "<2-3 sentences summary>",
"buggy_code": "<full buggy Java code>"
}}
```
"""
    return SYSTEM_V1, user_prompt


def enhance_bug_prompt_v1(code, buggy_code, test_info, specification):
    user_prompt = f"""
Below is the original Java code from a real project, followed by the natural-language specification that describes its intended behavior.

## Original code
```java
{code}
```

## Specification (intended behavior)
{_spec_text(specification)}

We have already generated a buggy version of the code:
```java
{buggy_code}
```

And the bug is detected by existing tests:
{test_info}

Your task is to generate another **buggy version** of the code.

## First, diagnose the detection
The detected tests caught the previous bug because it violated behavior that the specification pins down or that sits on a common boundary case (null / empty / unknown / duplicate / error handling on the main path). State that diagnosis for yourself, then choose a defect site AND mechanism of a different class:
- keep away from the code paths and input classes the detected tests exercise,
- prefer places where correctness depends on interactions of configuration flags, fallback/default chains, buffered vs resolved values, or order/state-dependent behavior that the specification does not explicitly pin down,
- the new buggy version must be different from the previous buggy version.

{ADVERSARY_SECTION}

## Goal
Create a buggy version of the code that:
- remains valid and compilable Java, with the same method signature and unit boundaries,
- different from the previous buggy version,
- exhibits incorrect behavior in at least one scenario that the adversary's next test suite will miss,
- differs from the original in one small, plausible edit.

{DEFECT_FORM_SECTION}

{NOEQUIV_SECTION_V1}

{STEALTH_SECTION}

## Output format

Return a JSON object exactly in the following format:

```json
{{
"bug_summary": "<2-3 sentences summary>",
"buggy_code": "<full buggy Java code>"
}}
```
"""
    return SYSTEM_V1, user_prompt




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


def init_bug_prompt_v2(code, specification):
    system, user = init_bug_prompt_v1(code, specification)
    return system, user.replace(NOEQUIV_SECTION_V1, NOEQUIV_SECTION)


def enhance_bug_prompt_v2(code, buggy_code, test_info, specification):
    system, user = enhance_bug_prompt_v1(code, buggy_code, test_info, specification)
    return system, user.replace(NOEQUIV_SECTION_V1, NOEQUIV_SECTION)


VERSIONS = {"v1": (init_bug_prompt_v1, enhance_bug_prompt_v1),
            "v2": (init_bug_prompt_v2, enhance_bug_prompt_v2),
            "v3": (init_bug_prompt_v3, enhance_bug_prompt_v3),
            "v4": (init_bug_prompt_v4, enhance_bug_prompt_v4),
            "v5": (init_bug_prompt_v5, enhance_bug_prompt_v5)}


def main():
    cmd = sys.argv[1]
    if cmd == "dump":
        version, out = sys.argv[2], sys.argv[3]
        init_fn, _ = VERSIONS[version]
        with open(DATA_PATH) as f:
            entries = json.load(f)
        dump = {}
        for i, e in enumerate(entries):
            system, user = init_fn(e["code"], e["specification"])
            dump[str(i)] = {"name": e["name"], "system": system, "user": user}
        with open(out, "w") as f:
            json.dump(dump, f, ensure_ascii=False, indent=1)
        print("dumped", len(dump))
    elif cmd == "dump-enhance":
        version, idx, buggy_file, testinfo_file, out = sys.argv[2:7]
        _, enh_fn = VERSIONS[version]
        with open(DATA_PATH) as f:
            entries = json.load(f)
        e = entries[int(idx)]
        buggy = open(buggy_file).read().strip()
        test_info = open(testinfo_file).read()
        system, user = enh_fn(e["code"], buggy, test_info, e["specification"])
        with open(out, "w") as f:
            json.dump({"system": system, "user": user}, f, ensure_ascii=False, indent=1)
        print("dumped enhance ->", out)
    else:
        raise SystemExit("unknown cmd")


if __name__ == "__main__":
    main()
