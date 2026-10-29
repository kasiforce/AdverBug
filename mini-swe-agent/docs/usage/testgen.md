# Function test generation

`mini-extra testgen` runs one fresh mini-SWE-agent Docker environment per function entry, extracts the complete generated test files, and writes them back to a result JSON file.

## Example

```bash
export OPENAI_API_KEY=...

mini-extra testgen \
  --dataset ../dataset/java/parser.json \
  --image adver-jsqlparser:test \
  --model openai/gpt-5-mini \
  --workers 2 \
  --output-dataset ../results/jsqlparser_with_tests.json \
  --output ../results/jsqlparser_trajectories
```

Use `--slice 0:2` for an initial smoke run. A mini-SWE-agent result is skipped only when it
submitted successfully, created the required test file, and made no disallowed changes. Failed or
policy-violating attempts are retried automatically. Legacy results that contain non-empty
`generated_tests` and no `mini_swe_agent` metadata remain compatible and are skipped. Pass
`--redo-existing` to run completed entries again.

The input must be a JSON array. Each entry needs at least these fields:

```json
{
  "project_root": "/path/to/project",
  "name": "target_function",
  "src_file": "relative/source/path.py",
  "test_file": "tests/generated/test_target_function.py",
  "code": "def target_function(...): ...",
  "type": "function",
  "start_line": 10,
  "end_line": 20
}
```

The output preserves every original field and adds:

- `generated_tests`: complete source code strings, compatible with the previous Copilot result format.
- `generated_config_files`: modified build or test configuration path and source code pairs.
- `mini_swe_agent`: execution status, image, language, modified files, policy violations, runtime, model cost, API calls, and trajectory path.

The original dataset is not modified unless the same path is explicitly passed to `--output-dataset`.

## Test isolation

Original test sources are removed inside every disposable container by default, before the agent starts. All three languages use the same directory-based rule: test source files below a directory named `test`, `tests`, `__test__`, `__tests__`, `spec`, `specs`, `androidTest`, or `testFixtures` are removed case-insensitively. Java removes `.java`, `.scala`, `.kt`, and `.groovy`, but always preserves `src/main`; Python removes `.py` except `conftest.py`; JavaScript removes `.js`, `.jsx`, `.mjs`, `.cjs`, `.ts`, and `.tsx`. Build descriptors and test resources such as `pom.xml`, JSON fixtures, and snapshots are preserved. Files outside those directories are preserved regardless of names such as `alphaTest.js` or `PerformanceTest.java`; there are no project-specific filename exceptions. Compiled test classes, test reports, generated test sources, Python bytecode caches, pytest caches, Jest caches, coverage output, and NYC output are also removed.

After deletion, the runner replaces the repository history with a single sanitized baseline commit. This prevents recovery through commands such as `git show` while retaining `git status` for mutation-policy auditing. The host checkout and Docker image are not changed. A deletion manifest and count are recorded under `mini_swe_agent.test_isolation`.

Use `--keep-existing-tests` only for an explicit ablation that allows access to the project's original tests.

Run `scripts/verify_test_isolation.py` to repeat the image-level check: it removes original tests in disposable containers, creates one new smoke test, and invokes each project's native test runner. The checked-in `docs/usage/test_isolation_report.json` records the latest result.

## Language-independent prompt

The benchmark uses one fixed task template for every supported language. The prompt receives only:

- the project-configured test framework;
- the complete target function or method source code;
- the production file path;
- the containing class name when the target is a method;
- the required test file path.

All behavioral requirements, quality constraints, file-mutation rules, execution instructions, and completion criteria are identical across languages. The template is defined as `LANGUAGE_AGNOSTIC_TASK_TEMPLATE` in `minisweagent.run.benchmarks.testgen`.

The defaults are JUnit 5 (Jupiter) for Java, pytest for Python, and Jest for JavaScript. A dataset entry may set `test_framework`, or a whole run can override it with `--test-framework`:

```bash
mini-extra testgen ... --test-framework "a project-specific test framework and runner"
```

Its design adapts focal-method context construction and generate-validate-repair from [ChatUniTest](https://github.com/ZJU-ACES-ISE/chatunitest-core), complete-test and execution-feedback principles from [CoverUp](https://github.com/plasma-umass/coverup), and failure-guided refinement from [TestPilot](https://github.com/githubnext/testpilot). These systems should be cited independently in publications; the benchmark template is an adaptation rather than a verbatim copy of any single prompt.

## Project examples

```bash
# Python
mini-extra testgen --dataset ../dataset/python/sqlglot.json --image adver-sqlglot:test -m openai/gpt-5-mini

# Java
mini-extra testgen --dataset ../dataset/java/fory.json --image adver-fory:test -m openai/gpt-5-mini

# JavaScript
mini-extra testgen --dataset ../dataset/js/eslint.json --image adver-eslint:test -m openai/gpt-5-mini
```

Set global safety limits when running a complete benchmark:

```bash
export MSWEA_GLOBAL_COST_LIMIT=100
export MSWEA_GLOBAL_CALL_LIMIT=5000
```
