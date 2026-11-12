import subprocess

import pytest

from minisweagent.run.benchmarks.testgen import (
    DEFAULT_CONFIG_FILE,
    INPUT_SCENARIOS,
    LANGUAGE_AGNOSTIC_TASK_TEMPLATE,
    TARGET_SCOPE_INSTRUCTIONS,
    TARGET_SCOPE_PROMPT_VERSION,
    apply_target_budget,
    build_task,
    build_test_artifact_find_command,
    build_test_file_find_command,
    infer_language,
    is_allowed_modified_path,
    is_build_or_test_config_path,
    is_completed_result,
    make_instance_id,
    parse_modified_files,
    replace_unique_code,
    resolve_test_framework,
    resolve_test_output,
    resolve_target_type,
    validate_test_path,
)


@pytest.fixture
def java_entry():
    return {
        "project_root": "/projects/demo",
        "name": "render",
        "src_file": "src/main/java/demo/Renderer.java",
        "test_file": "src/test/java/demo/RendererTest.java",
        "code": 'String render() { return "ok"; }',
        "start_line": 10,
        "end_line": 12,
        "type": "method",
        "class_name": "Renderer",
    }


def test_infer_language(java_entry):
    assert infer_language(java_entry) == "java"
    assert infer_language({"src_file": "pkg/module.py"}) == "python"
    assert infer_language({"src_file": "src/parser.js"}) == "javascript"
    assert infer_language({"src_file": "src/parser.mjs"}) == "javascript"
    assert infer_language({"src_file": "src/component.jsx"}) == "javascript"
    assert infer_language(java_entry, "js") == "javascript"
    assert infer_language({"language": "js", "module": "demo/rendering"}) == "javascript"
    assert infer_language({"target_type": "module", "files": ["demo/rendering/api.ts"]}) == "javascript"


def test_validate_test_path():
    assert str(validate_test_path("tests/test_demo.py")) == "tests/test_demo.py"
    with pytest.raises(ValueError):
        validate_test_path("../source.py")
    with pytest.raises(ValueError):
        validate_test_path("/tmp/test.py")


def test_test_file_find_command_uses_shared_test_directories_and_language_prunes():
    java = build_test_file_find_command("java", delete=True)
    python = build_test_file_find_command("python", delete=True)
    javascript = build_test_file_find_command("javascript", delete=True)
    for command in (java, python, javascript):
        assert "*/test/*" in command and "*/tests/*" in command
        assert "*/__test__/*" in command and "*/__tests__/*" in command
        assert "*/spec/*" in command and "*/specs/*" in command
        assert "*/androidTest/*" in command and "*/testFixtures/*" in command
        assert "*/gen_tests/*" not in command
        assert "*Test.js" not in command and "*test_*" not in command
    assert "*.java" in java and "*.kt" in java and "*.groovy" in java
    assert "! -ipath '*/src/main/*'" in java
    assert "! -iname conftest.py" in python
    assert "*.mjs" in javascript and "*.tsx" in javascript
    assert "-name .git" in java and "-name node_modules" not in java
    assert "-name node_modules" in javascript
    assert java.endswith("-print -exec rm -f -- {} +")
    with pytest.raises(ValueError):
        build_test_file_find_command("unknown")


def test_artifact_cleanup_removes_only_test_outputs_and_python_caches():
    command = build_test_artifact_find_command(delete=True)
    assert "*/target/test-classes" in command
    assert "*/build/classes/java/test" in command
    assert "*/__pycache__" in command
    assert "*/coverage" in command
    assert "*/node_modules/.cache/jest" in command
    assert "*/target/classes" not in command
    assert "*/build/classes/java/main" not in command
    assert command.endswith("-exec rm -rf -- {} +")
    assert build_test_artifact_find_command().endswith("-print")


def test_build_task_enforces_target(java_entry):
    task = build_task(java_entry, "java")
    assert "src/test/java/demo/RendererTest.java" in task
    assert "String render()" in task
    assert "Production file:\nsrc/main/java/demo/Renderer.java" in task
    assert "Target class:\nRenderer" in task
    assert "Test target:\nTarget function or method:" in task
    assert "Testing focus:" in task
    assert TARGET_SCOPE_INSTRUCTIONS["function"] in task
    assert "MUST write the complete generated test suite to exactly" in task
    assert "<target_code>" in task and "</target_code>" in task


def test_build_task_includes_specification_when_present(java_entry):
    java_entry["specification"] = "Returns the rendered value and propagates dependency failures."
    task = build_task(java_entry, "java", input_scenario="source-code-plus-specification")
    assert (
        "Behavioral specification:\n<specification>\n"
        "Returns the rendered value and propagates dependency failures.\n</specification>"
    ) in task
    assert task.index("Behavioral specification:") < task.index("Testing focus:")


def test_build_task_rejects_missing_required_specification(java_entry):
    java_entry["specification"] = "  "
    with pytest.raises(ValueError, match="requires a non-empty 'specification'"):
        build_task(java_entry, "java", input_scenario="source-code-plus-specification")


@pytest.mark.parametrize(
    ("scenario", "has_source", "has_buggy", "has_specification"),
    [
        ("source-code-only", True, False, False),
        ("source-code-plus-specification", True, False, True),
        ("buggy-code-only", False, True, False),
        ("buggy-code-plus-specification", False, True, True),
        ("specification-only", False, False, True),
    ],
)
def test_build_task_supports_five_input_scenarios(
    java_entry, scenario, has_source, has_buggy, has_specification
):
    java_entry.update(
        {
            "specification": "The renderer returns the dependency value.",
            "buggy_code": ['String render() { return "wrong"; }'],
        }
    )
    task = build_task(java_entry, "java", input_scenario=scenario)
    assert ('return "ok"' in task) is has_source
    assert ('return "wrong"' in task) is has_buggy
    assert ("Behavioral specification:" in task) is has_specification
    assert "Input evidence boundary:" in task
    assert "Do not read the target function from its production file" in task
    assert ("<target_code>" in task) is (has_source or has_buggy)
    assert set(INPUT_SCENARIOS) == {
        "source-code-only",
        "source-code-plus-specification",
        "buggy-code-only",
        "buggy-code-plus-specification",
        "specification-only",
    }


def test_build_task_selects_requested_buggy_code(java_entry):
    java_entry["buggy_code"] = ["first buggy version", "second buggy version"]
    task = build_task(java_entry, "java", input_scenario="buggy-code-only", buggy_code_index=1)
    assert "second buggy version" in task
    assert "first buggy version" not in task
    with pytest.raises(ValueError, match="out of range"):
        build_task(java_entry, "java", input_scenario="buggy-code-only", buggy_code_index=2)


def test_replace_unique_code_requires_one_distinct_match():
    source = "class Demo { int target() { return 1; } }"
    original = "int target() { return 1; }"
    buggy = "int target() { return 2; }"
    assert replace_unique_code(source, original, buggy) == (
        "class Demo { int target() { return 2; } }"
    )
    with pytest.raises(ValueError, match="occurs 0 times"):
        replace_unique_code(source, "missing", buggy)
    with pytest.raises(ValueError, match="must differ"):
        replace_unique_code(source, original, original)


def test_build_task_selects_only_source_file_scope():
    entry = {
        "project_root": "/projects/demo",
        "target_type": "source_file",
        "src_file": "demo/renderer.py",
        "test_file": "tests/generated/test_renderer.py",
    }
    task = build_task(entry, "python")
    assert "Test target:\nProduction source file:" in task
    assert "Production source file:\ndemo/renderer.py" in task
    assert TARGET_SCOPE_INSTRUCTIONS["source_file"] in task
    assert TARGET_SCOPE_INSTRUCTIONS["function"] not in task
    assert TARGET_SCOPE_INSTRUCTIONS["module"] not in task


def test_build_task_selects_only_module_scope():
    entry = {
        "project_root": "/projects/demo",
        "target_type": "module",
        "module": "demo/rendering",
        "files": ["demo/rendering/api.py", "demo/rendering/core.py"],
        "test_module": "tests/generated/rendering",
    }
    task = build_task(entry, "python")
    assert "Test target:\nModule:" in task
    assert "Module:\ndemo/rendering" in task
    assert "complete module test scope" in task
    assert "- demo/rendering/api.py" in task and "- demo/rendering/core.py" in task
    assert "Required test module:" in task
    assert "every generated test file under exactly `tests/generated/rendering`" in task
    assert TARGET_SCOPE_INSTRUCTIONS["module"] in task
    assert TARGET_SCOPE_INSTRUCTIONS["function"] not in task
    assert TARGET_SCOPE_INSTRUCTIONS["source_file"] not in task


def test_build_task_describes_recursive_module_scope():
    entry = {
        "project_root": "/projects/demo",
        "target_type": "module",
        "module": "demo/rendering",
        "module_scope": "recursive_directory",
        "files": ["demo/rendering/api.py", "demo/rendering/core/helpers.py"],
        "test_module": "tests/generated/rendering",
    }
    task = build_task(entry, "python")
    assert "This directory is a recursive module." in task
    assert "complete test scope" in task
    assert "do not test repository files outside this list" in task


def test_resolve_target_type_is_structured_and_backwards_compatible():
    assert resolve_target_type({"type": "function"}) == "function"
    assert resolve_target_type({"type": "method"}) == "function"
    assert resolve_target_type({"target_type": "source_file"}) == "source_file"
    assert resolve_target_type({"target_type": "module"}) == "module"
    assert resolve_target_type({"module": "demo/rendering"}) == "module"
    assert resolve_target_type({"src_file": "demo/render.py"}) == "source_file"
    with pytest.raises(ValueError, match="Unsupported target type"):
        resolve_target_type({"target_type": "package"})


def test_resolve_test_output_uses_a_file_except_for_modules(java_entry):
    assert resolve_test_output(java_entry) == (validate_test_path(java_entry["test_file"]), False)
    assert resolve_test_output(
        {"target_type": "module", "test_module": "tests/generated/rendering"}
    ) == (validate_test_path("tests/generated/rendering"), True)
    with pytest.raises(ValueError, match="test_file must be a safe relative path"):
        resolve_test_output({"target_type": "module", "test_file": "tests/test_module.py"})


def test_target_code_can_contain_markdown_fences(java_entry):
    java_entry["code"] = 'String render() { return "```java"; }'
    task = build_task(java_entry, "java")
    assert 'return "```java"' in task
    assert task.count("<target_code>") == task.count("</target_code>") == 1


def test_build_task_omits_unneeded_exploration_context(java_entry):
    java_entry.update(
        {
            "full_class_name": "demo.Renderer",
            "class_constructor": "Renderer(Dependency dependency)",
            "class_fields": ["Dependency dependency"],
            "is_static": False,
            "imports": ["demo.Dependency"],
            "specification": "Generated specification",
        }
    )
    task = build_task(java_entry, "java", input_scenario="source-code-plus-specification")
    assert "Target class:\ndemo.Renderer" in task
    assert "Behavioral specification:" in task
    assert "Generated specification" in task
    for omitted in (
        "Context:",
        "target_lines",
        "function_type",
        "class_context",
        "relevant_imports",
        "demo.Dependency",
    ):
        assert omitted not in task


def test_prompt_template_is_language_independent(java_entry):
    assert "java" not in LANGUAGE_AGNOSTIC_TASK_TEMPLATE.lower()
    assert "python" not in LANGUAGE_AGNOSTIC_TASK_TEMPLATE.lower()
    assert "junit" not in LANGUAGE_AGNOSTIC_TASK_TEMPLATE.lower()
    assert "pytest" not in LANGUAGE_AGNOSTIC_TASK_TEMPLATE.lower()

    python_entry = {
        **java_entry,
        "name": "render",
        "src_file": "demo/renderer.py",
        "test_file": "tests/test_renderer.py",
        "code": 'def render():\n    return "ok"',
        "type": "function",
        "class_name": None,
    }
    java_task = build_task(java_entry, "java")
    python_task = build_task(python_entry, "python")
    assert "JUnit 5" in java_task and "pytest" not in java_task
    assert "pytest" in python_task and "JUnit" not in python_task


def test_testgen_config_contains_generation_policy():
    config = DEFAULT_CONFIG_FILE.read_text(encoding="utf-8")
    assert "DO NOT READ existing" in config
    assert "minimally modify a relevant build" in config
    assert "test-scoped or development-only" in config
    assert "Use meaningful assertions" in config
    assert "install global tools" in config
    assert "Run only the generated test file or test module when practical" in config
    assert "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" in config
    assert "at least one bash tool call" in config
    assert "parallel_tool_calls: true" in config
    assert "The output of your last command was too long" in config
    assert 'finish_reason == "length"' in config
    assert DEFAULT_CONFIG_FILE.name == "testgen_target_scoped.yaml"
    assert TARGET_SCOPE_PROMPT_VERSION == "4"


def test_target_scopes_receive_separate_resource_budgets():
    config = {
        "agent": {"step_limit": 200, "cost_limit": 1.0, "wall_time_limit_seconds": 2400},
        "environment": {"timeout": 600, "container_timeout": "1h"},
        "target_budgets": {
            "function": {
                "agent": {"step_limit": 120, "cost_limit": 0.25, "wall_time_limit_seconds": 1200},
                "environment": {"container_timeout": "35m"},
            },
            "source_file": {
                "agent": {"step_limit": 160, "cost_limit": 0.5, "wall_time_limit_seconds": 1800},
                "environment": {"container_timeout": "45m"},
            },
        },
    }
    function = apply_target_budget(config, "function")
    source_file = apply_target_budget(config, "source_file")
    module = apply_target_budget(config, "module")
    assert function["agent"] == {"step_limit": 120, "cost_limit": 0.25, "wall_time_limit_seconds": 1200}
    assert function["environment"] == {"timeout": 600, "container_timeout": "35m"}
    assert source_file["agent"] == {"step_limit": 160, "cost_limit": 0.5, "wall_time_limit_seconds": 1800}
    assert source_file["environment"] == {"timeout": 600, "container_timeout": "45m"}
    assert module["agent"] == {"step_limit": 200, "cost_limit": 1.0, "wall_time_limit_seconds": 2400}
    assert "target_budgets" not in function and "target_budgets" not in module
    assert config["agent"]["step_limit"] == 200


@pytest.mark.parametrize(
    ("path",),
    [
        ("pom.xml",),
        ("module/pom.xml",),
        ("build.gradle.kts",),
        ("pyproject.toml",),
        ("requirements-test.txt",),
        ("package.json",),
        ("jest.config.cjs",),
    ],
)
def test_build_and_test_configuration_paths_are_allowed(path):
    assert is_build_or_test_config_path(path)
    assert is_allowed_modified_path(path, "tests/generated/test_target.py")


def test_production_and_ci_files_remain_policy_violations():
    target = "tests/generated/test_target.py"
    assert is_allowed_modified_path(target, target)
    assert not is_allowed_modified_path("tests/generated/test_other.py", target)
    assert not is_allowed_modified_path("src/main/java/demo/Renderer.java", target)
    assert not is_allowed_modified_path("src/demo/renderer.py", target)
    assert not is_allowed_modified_path("src/contest.js", target)
    assert not is_allowed_modified_path("src/latest.py", target)
    assert not is_allowed_modified_path("src/TestParser.java", target)
    assert not is_allowed_modified_path(
        "lib/testing/thymeleaf-testing/src/main/java/example/StandardTestableResolver.java", target
    )
    assert not is_allowed_modified_path(".github/workflows/tests.yml", target)


def test_module_output_allows_only_files_below_the_required_test_module():
    target = "tests/generated/rendering"
    assert is_allowed_modified_path("tests/generated/rendering/test_api.py", target, output_is_module=True)
    assert is_allowed_modified_path("tests/generated/rendering/workflows/test_flow.py", target, output_is_module=True)
    assert not is_allowed_modified_path("tests/generated/rendering_extra/test_api.py", target, output_is_module=True)
    assert not is_allowed_modified_path("tests/generated/test_api.py", target, output_is_module=True)


def test_completed_result_requires_successful_policy_compliant_submission():
    result = {
        "generated_tests": ["test code"],
        "mini_swe_agent": {
            "exit_status": "Submitted",
            "test_file_created": True,
            "policy_violations": [],
        },
    }
    assert is_completed_result(result)
    assert is_completed_result({"generated_tests": ["legacy result"]})
    for key, value in (
        ("exit_status", "LimitsExceeded"),
        ("test_file_created", False),
        ("policy_violations", ["src/main.py"]),
    ):
        failed = {**result, "mini_swe_agent": {**result["mini_swe_agent"], key: value}}
        assert not is_completed_result(failed)


def test_completed_result_is_scoped_to_input_scenario():
    result = {
        "generated_tests": ["test code"],
        "mini_swe_agent": {
            "exit_status": "Submitted",
            "test_file_created": True,
            "policy_violations": [],
            "input_scenario": "buggy-code-only",
            "buggy_code_index": 1,
        },
    }
    assert is_completed_result(result, "buggy-code-only", 1)
    assert not is_completed_result(result, "buggy-code-only", 0)
    assert not is_completed_result(result, "source-code-only")
    assert not is_completed_result({"generated_tests": ["legacy result"]}, "source-code-only")


def test_framework_can_come_from_entry_or_cli_override(java_entry):
    java_entry["test_framework"] = "TestNG configured by this project"
    assert resolve_test_framework(java_entry, "java") == "TestNG configured by this project"
    task = build_task(java_entry, "java")
    assert "TestNG configured by this project" in task
    assert "JUnit" not in task

    override = "a custom in-project test framework"
    assert resolve_test_framework(java_entry, "java", override) == override
    assert override in build_task(java_entry, "java", test_framework=override)


def test_javascript_task_uses_jest(java_entry):
    entry = {
        **java_entry,
        "src_file": "src/renderer.mjs",
        "test_file": "test/generated/renderer.test.mjs",
        "code": "export function render() { return 'ok'; }",
        "type": "function",
        "class_name": None,
    }
    task = build_task(entry, infer_language(entry))
    assert "Jest" in task
    assert "test/generated/renderer.test.mjs" in task
    assert "Target class:" not in task


def test_javascript_test_deletion_is_directory_based(tmp_path):
    removed = [
        "test/unit/parser.js",
        "tests/math.test.mjs",
        "src/__tests__/renderer.cjs",
        "spec/widget.spec.jsx",
        "tests/setup.js",
    ]
    preserved = [
        "src/test-parser.js",
        "src/test_parser.ts",
        "TestParser.js",
        "parserTest.js",
        "src/parser_test.helper.js",
        "src/parser.test-d.ts",
        "src/parser.tests.js",
        "src/parser_spec.js",
        "src/alphaTest.js",
        "src/widget.spec.jsx",
        "src/main.js",
        "tests/renderer.snap",
        "test/fixtures/input.json",
        "jest.config.js",
        "src/contest.js",
        "src/latest.js",
    ]
    for relative in removed + preserved:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content", encoding="utf-8")
    assert subprocess.run(
        build_test_file_find_command("javascript", delete=True),
        cwd=tmp_path,
        shell=True,
        check=False,
        capture_output=True,
        text=True,
    ).returncode == 0
    assert all(not (tmp_path / relative).exists() for relative in removed)
    assert all((tmp_path / relative).exists() for relative in preserved)


def test_java_test_deletion_is_directory_based(tmp_path):
    removed = [
        "module/src/test/java/RendererTest.java",
        "module/tests/ParserSpec.scala",
        "module/TEST/UppercaseTest.java",
        "module/src/androidTest/java/InstrumentedTest.java",
        "module/src/testFixtures/kotlin/Fixture.kt",
    ]
    preserved = [
        "module/src/main/java/RendererTest.java",
        "module/src/main/java/demo/test/TestSupport.java",
        "module/testing/ParserTest.java",
        "module/tests/pom.xml",
        "module/src/testFixtures/resources/cases.json",
    ]
    for relative in removed + preserved:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content", encoding="utf-8")
    assert subprocess.run(
        build_test_file_find_command("java", delete=True),
        cwd=tmp_path,
        shell=True,
        check=False,
        capture_output=True,
        text=True,
    ).returncode == 0
    assert all(not (tmp_path / relative).exists() for relative in removed)
    assert all((tmp_path / relative).exists() for relative in preserved)


def test_python_test_deletion_is_directory_based(tmp_path):
    removed = [
        "tests/test_parser.py",
        "test/parser_test_helpers.py",
        "TEST/test_uppercase.py",
    ]
    preserved = [
        "src/test_parser.py",
        "gen_tests/contest_utils.py",
        "tests/conftest.py",
        "tests/fixtures/cases.json",
    ]
    for relative in removed + preserved:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content", encoding="utf-8")
    assert subprocess.run(
        build_test_file_find_command("python", delete=True),
        cwd=tmp_path,
        shell=True,
        check=False,
        capture_output=True,
        text=True,
    ).returncode == 0
    assert all(not (tmp_path / relative).exists() for relative in removed)
    assert all((tmp_path / relative).exists() for relative in preserved)


def test_instance_id_and_status_parsing(java_entry):
    assert make_instance_id(java_entry, 3) == "demo__render__10__3"
    assert parse_modified_files("?? tests/test_a.py\n M src/main.py\n") == ["tests/test_a.py", "src/main.py"]
