#!/usr/bin/env python3

"""Generate tests for function-level benchmark entries with mini-SWE-agent."""

import concurrent.futures
import copy
import json
import re
import shlex
import subprocess
import threading
import time
import traceback
from pathlib import Path, PurePosixPath

import typer
from rich.live import Live

from minisweagent.config import builtin_config_dir, get_config_from_spec
from minisweagent.environments import get_environment
from minisweagent.models import get_model
from minisweagent.run.benchmarks.swebench import filter_instances
from minisweagent.run.benchmarks.utils.batch_progress import RunBatchProgressManager
from minisweagent.run.benchmarks.utils.common import ProgressTrackingAgent
from minisweagent.utils.log import add_file_handler, logger
from minisweagent.utils.serialize import UNSET, recursive_merge

DEFAULT_CONFIG_FILE = builtin_config_dir / "benchmarks" / "testgen.yaml"
app = typer.Typer(rich_markup_mode="rich", add_completion=False)
_RESULTS_LOCK = threading.Lock()
_RUN_ARTIFACTS_LOCK = threading.Lock()

TEST_FRAMEWORKS = {
    "java": "JUnit 5",
    "python": "pytest",
    "javascript": "Jest",
}

LANGUAGE_AGNOSTIC_TASK_TEMPLATE = """Testing framework:
{test_framework}

Target function:
{target_function}

Production file:
{production_file}

{target_class}

Required test file:
You MUST write the complete generated test suite to exactly `{required_test_file}`.
"""

TEST_DIRECTORY_NAMES = (
    "test",
    "tests",
    "__test__",
    "__tests__",
    "spec",
    "specs",
    "androidTest",
    "testFixtures",
)

TEST_SOURCE_EXPRESSIONS = {
    "java": (
        r"! -ipath '*/src/main/*' "
        r"\( -name '*.java' -o -name '*.scala' -o -name '*.kt' -o -name '*.groovy' \)"
    ),
    "python": r"-name '*.py' ! -iname conftest.py",
    "javascript": (
        r"\( -name '*.js' -o -name '*.jsx' -o -name '*.mjs' -o -name '*.cjs' "
        r"-o -name '*.ts' -o -name '*.tsx' \)"
    ),
}

TEST_FILE_PRUNE_DIR_NAMES = {
    "java": (".git", "venv", ".venv", "__pycache__"),
    "python": (".git", "venv", ".venv", "__pycache__"),
    "javascript": (".git", "node_modules", "dist", "build"),
}

TEST_ARTIFACT_DIR_NAMES = (
    "*/target/test-classes",
    "*/target/generated-test-sources",
    "*/target/surefire-reports",
    "*/target/failsafe-reports",
    "*/build/classes/java/test",
    "*/build/classes/kotlin/test",
    "*/build/classes/groovy/test",
    "*/build/resources/test",
    "*/build/test-results",
    "*/build/reports/tests",
    "*/__pycache__",
    "*/.pytest_cache",
    "*/coverage",
    "*/.nyc_output",
    "*/.jest-cache",
    "*/.cache/jest",
    "*/node_modules/.cache/jest",
)

BUILD_OR_TEST_CONFIG_FILENAMES = {
    "build.gradle",
    "build.gradle.kts",
    "gradle.properties",
    "libs.versions.toml",
    "maven.config",
    "pom.xml",
    "settings.gradle",
    "settings.gradle.kts",
    "pipfile",
    "pipfile.lock",
    "poetry.lock",
    "pyproject.toml",
    "pytest.ini",
    "setup.cfg",
    "setup.py",
    "tox.ini",
    "uv.lock",
    "npm-shrinkwrap.json",
    "package-lock.json",
    "package.json",
    "pnpm-lock.yaml",
    "yarn.lock",
}


def infer_language(entry: dict, requested: str = "auto") -> str:
    if requested != "auto":
        language = requested.lower()
        return "javascript" if language in {"js", "javascript"} else language
    suffix = Path(entry.get("src_file", "")).suffix.lower()
    if suffix == ".java":
        return "java"
    if suffix == ".py":
        return "python"
    if suffix in {".js", ".jsx", ".mjs", ".cjs"}:
        return "javascript"
    raise ValueError(f"Cannot infer language from src_file={entry.get('src_file')!r}")


def validate_test_path(test_file: str) -> PurePosixPath:
    path = PurePosixPath(test_file)
    if not test_file or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"test_file must be a safe relative path, got {test_file!r}")
    return path


def build_test_file_find_command(language: str, *, delete: bool = False) -> str:
    try:
        prune_names = TEST_FILE_PRUNE_DIR_NAMES[language]
        source_expression = TEST_SOURCE_EXPRESSIONS[language]
    except KeyError as error:
        raise ValueError(f"Unsupported language: {language!r}") from error
    action = "-print -exec rm -f -- {} +" if delete else "-print"
    prunes = " -o ".join(f"-name {shlex.quote(name)}" for name in prune_names)
    test_paths = " -o ".join(
        f"-ipath {shlex.quote(f'*/{directory_name}/*')}" for directory_name in TEST_DIRECTORY_NAMES
    )
    return (
        "find . "
        rf"\( -type d \( {prunes} \) \) -prune -o "
        rf"-type f \( {test_paths} \) {source_expression} {action}"
    )


def build_test_artifact_find_command(*, delete: bool = False) -> str:
    paths = " -o ".join(f"-path {shlex.quote(path)}" for path in TEST_ARTIFACT_DIR_NAMES)
    action = "-exec rm -rf -- {} +" if delete else "-print"
    return f"find . -depth -type d \\( {paths} \\) {action}"


def remove_existing_tests(env, language: str) -> list[str]:
    listing = env.execute({"command": build_test_file_find_command(language)})
    if listing["returncode"] != 0:
        raise RuntimeError(f"Failed to enumerate existing tests: {listing['output']}")
    files = [line.removeprefix("./") for line in listing["output"].splitlines() if line.strip()]
    deletion = env.execute({"command": build_test_file_find_command(language, delete=True)})
    if deletion["returncode"] != 0:
        raise RuntimeError(f"Failed to delete existing tests: {deletion['output']}")
    artifact_cleanup = env.execute({"command": build_test_artifact_find_command(delete=True)})
    if artifact_cleanup["returncode"] != 0:
        raise RuntimeError(f"Failed to delete compiled test artifacts: {artifact_cleanup['output']}")

    # Removing only the working-tree files is insufficient: an agent could recover them with
    # `git show`. Reinitialize a history-free repository while preserving status-based auditing.
    reinitialize = env.execute(
        {
            "command": (
                "rm -rf /testbed/.git && git init -q /testbed && "
                "git -C /testbed config user.name benchmark && "
                "git -C /testbed config user.email benchmark@localhost && "
                "git -C /testbed add -A && "
                "git -C /testbed -c core.hooksPath=/dev/null commit -q --no-gpg-sign -m sanitized-baseline"
            )
        }
    )
    if reinitialize["returncode"] != 0:
        raise RuntimeError(f"Failed to create sanitized Git baseline: {reinitialize['output']}")
    return files


def make_instance_id(entry: dict, index: int) -> str:
    project = Path(entry.get("project_root", "project")).name or "project"
    raw = f"{project}__{entry.get('name', 'function')}__{entry.get('start_line', index)}__{index}"
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", raw)


def resolve_test_framework(entry: dict, language: str, override: str | None = None) -> str:
    if override:
        return override
    if entry.get("test_framework"):
        return str(entry["test_framework"])
    try:
        return TEST_FRAMEWORKS[language]
    except KeyError as error:
        raise ValueError(f"Unsupported language: {language!r}") from error


def build_task(
    entry: dict,
    language: str,
    test_framework: str | None = None,
) -> str:
    test_file = validate_test_path(entry.get("test_file", ""))
    resolved_framework = resolve_test_framework(entry, language, test_framework)
    target_function = f"""<target_code>
{entry.get("code", "")}
</target_code>"""
    target_class = entry.get("full_class_name") or entry.get("class_name")
    return LANGUAGE_AGNOSTIC_TASK_TEMPLATE.format(
        test_framework=resolved_framework,
        target_function=target_function,
        production_file=entry.get("src_file", ""),
        target_class=f"\nTarget class:\n{target_class}\n" if target_class else "",
        required_test_file=test_file,
    )


def parse_modified_files(status: str) -> list[str]:
    files = []
    for line in status.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1]
        files.append(path.strip('"'))
    return files


def is_build_or_test_config_path(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return (
        name in BUILD_OR_TEST_CONFIG_FILENAMES
        or (name.startswith("requirements") and name.endswith(".txt"))
        or name.startswith(("jest.config.", "babel.config."))
    )


def is_allowed_modified_path(path: str, required_test_file: str | PurePosixPath) -> bool:
    if any(part.lower() in {".circleci", ".github", ".gitlab"} for part in PurePosixPath(path).parts):
        return False
    return PurePosixPath(path) == PurePosixPath(required_test_file) or is_build_or_test_config_path(path)


def is_completed_result(result: dict) -> bool:
    if not result.get("generated_tests"):
        return False
    metadata = result.get("mini_swe_agent")
    if not isinstance(metadata, dict):
        return True
    return (
        metadata.get("exit_status") == "Submitted"
        and metadata.get("test_file_created") is True
        and not metadata.get("policy_violations")
    )


def copy_container_file(env, container_path: PurePosixPath, destination: Path) -> str:
    container_id = getattr(env, "container_id", None)
    executable = getattr(getattr(env, "config", None), "executable", None)
    if not container_id or not executable:
        raise RuntimeError("Docker container information is unavailable")
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [executable, "cp", f"{container_id}:{container_path}", str(destination)],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        return destination.read_text(encoding="utf-8")
    finally:
        destination.unlink(missing_ok=True)


def write_results(path: Path, results: list[dict]) -> None:
    with _RESULTS_LOCK:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)


def write_run_artifact(output_dir: Path, filename: str, key: str, value: object) -> None:
    """Store per-instance run data in one project-level JSON file."""
    path = output_dir / filename
    with _RUN_ARTIFACTS_LOCK:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        data[key] = value
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)


def compact_trajectory(data: dict) -> dict:
    """Remove reproducible configuration from the persisted trajectory."""
    info = data.get("info")
    if isinstance(info, dict):
        info.pop("config", None)
    return data


def process_instance(
    instance: dict,
    results: list[dict],
    output_dataset: Path,
    output_dir: Path,
    config: dict,
    image: str,
    language: str,
    test_framework: str | None,
    remove_tests: bool,
    progress_manager: RunBatchProgressManager,
) -> None:
    index = instance["_index"]
    instance_id = instance["instance_id"]
    test_path = validate_test_path(instance["test_file"])
    progress_manager.on_instance_start(instance_id)
    progress_manager.update_instance_status(instance_id, "Starting environment")

    env = None
    agent = None
    exit_status = "InfrastructureError"
    error_info: dict = {}
    generated_files: list[dict] = []
    generated_config_files: list[dict] = []
    modified_files: list[str] = []
    removed_test_files: list[str] = []
    started = time.monotonic()
    try:
        instance_config = copy.deepcopy(config)
        environment_config = instance_config.setdefault("environment", {})
        environment_config["image"] = image
        environment_config.setdefault("cwd", "/testbed")
        env = get_environment(environment_config, default_type="docker")
        if remove_tests:
            removed_test_files = remove_existing_tests(env, language)
            # All instances of a project run against the same clean checkout.
            # Keep one isolation manifest for the whole project, not one per function.
            manifest = output_dir / "removed_original_tests.json"
            with _RUN_ARTIFACTS_LOCK:
                if not manifest.exists():
                    manifest.write_text(
                        json.dumps(removed_test_files, indent=2, ensure_ascii=False), encoding="utf-8"
                    )
        target = PurePosixPath("/testbed") / test_path
        setup = env.execute(
            {"command": f"mkdir -p {shlex.quote(str(target.parent))} && rm -f {shlex.quote(str(target))}"}
        )
        if setup["returncode"] != 0:
            raise RuntimeError(f"Failed to prepare target test path: {setup['output']}")

        model = get_model(config=instance_config.get("model", {}))
        agent_config = dict(instance_config.get("agent", {}))
        # Keep trajectories in one project-level JSON instead of creating one
        # directory and trajectory file for every target function.
        agent_config["output_path"] = None
        agent = ProgressTrackingAgent(
            model,
            env,
            progress_manager=progress_manager,
            instance_id=instance_id,
            **agent_config,
        )
        info = agent.run(build_task(instance, language, test_framework), instance=instance)
        exit_status = info.get("exit_status", "")

        status = env.execute({"command": "git status --porcelain --untracked-files=all"})
        modified_files = parse_modified_files(status["output"])
        for position, path in enumerate([str(test_path)]):
            safe_path = validate_test_path(path)
            exists = env.execute({"command": f"test -f {shlex.quote(str(PurePosixPath('/testbed') / safe_path))}"})
            if exists["returncode"] != 0:
                continue
            suffix = safe_path.suffix or ".txt"
            generated_files.append(
                {
                    "path": str(safe_path),
                    "code": copy_container_file(
                        env,
                        PurePosixPath("/testbed") / safe_path,
                        output_dir / f".{instance_id}.generated_{position}{suffix}",
                    ),
                }
            )
        config_paths = dict.fromkeys(path for path in modified_files if is_build_or_test_config_path(path))
        for position, path in enumerate(config_paths):
            safe_path = validate_test_path(path)
            exists = env.execute(
                {"command": f"test -f {shlex.quote(str(PurePosixPath('/testbed') / safe_path))}"}
            )
            if exists["returncode"] != 0:
                continue
            suffix = safe_path.suffix or ".txt"
            generated_config_files.append(
                {
                    "path": str(safe_path),
                    "code": copy_container_file(
                        env,
                        PurePosixPath("/testbed") / safe_path,
                        output_dir / f".{instance_id}.generated_config_{position}{suffix}",
                    ),
                }
            )
    except Exception as error:
        logger.error("Error processing %s: %s", instance_id, error, exc_info=True)
        exit_status = type(error).__name__
        error_info = {"exception": str(error), "traceback": traceback.format_exc()}
    finally:
        elapsed = time.monotonic() - started
        trajectory = None
        if agent is not None:
            trajectory = agent.save(
                None,
                {"info": {"exit_status": exit_status, **error_info}, "instance_id": instance_id},
            )
            trajectory = compact_trajectory(trajectory)
            write_run_artifact(output_dir, "trajectories.json", instance_id, trajectory)
        result = dict(results[index])
        result["generated_tests"] = [item["code"] for item in generated_files]
        result.pop("generated_test_files", None)
        result["generated_config_files"] = generated_config_files
        result["mini_swe_agent"] = {
            "instance_id": instance_id,
            "image": image,
            "language": language,
            "test_framework": resolve_test_framework(instance, language, test_framework),
            "test_isolation": {
                "existing_tests_removed": remove_tests,
                "removed_test_file_count": len(removed_test_files),
                "git_history_reinitialized": remove_tests,
                "manifest": str(output_dir / "removed_original_tests.json") if remove_tests else None,
            },
            "exit_status": exit_status,
            "test_file_created": any(item["path"] == str(test_path) for item in generated_files),
            "modified_files": modified_files,
            "policy_violations": [
                path for path in modified_files if not is_allowed_modified_path(path, test_path)
            ],
            "time_seconds": elapsed,
            "model_cost": agent.cost if agent is not None else 0.0,
            "api_calls": agent.n_calls if agent is not None else 0,
            "trajectory": str(output_dir / "trajectories.json"),
            **error_info,
        }
        results[index] = result
        write_results(output_dataset, results)
        if env is not None:
            env.cleanup()
        progress_manager.on_instance_end(instance_id, exit_status)


@app.command()
def main(
    dataset: Path = typer.Option(..., "--dataset", exists=True, readable=True, help="Input function dataset JSON"),
    image: str = typer.Option(..., "--image", help="Docker image containing the clean project"),
    output_dataset: Path | None = typer.Option(None, "--output-dataset", help="Result JSON with generated test code"),
    output: Path | None = typer.Option(None, "-o", "--output", help="Trajectory and extracted-file directory"),
    language: str = typer.Option("auto", "--language", help="auto, java, python, or javascript/js"),
    test_framework: str | None = typer.Option(
        None,
        "--test-framework",
        help="Override framework description; otherwise use entry.test_framework or language default",
    ),
    slice_spec: str = typer.Option("", "--slice", help="Python slice, for example 0:5"),
    filter_spec: str = typer.Option("", "--filter", help="Instance ID regular expression"),
    shuffle: bool = typer.Option(False, "--shuffle", help="Shuffle deterministically"),
    workers: int = typer.Option(1, "-w", "--workers", min=1),
    model: str | None = typer.Option(None, "-m", "--model"),
    model_class: str | None = typer.Option(None, "--model-class"),
    redo_existing: bool = typer.Option(False, "--redo-existing"),
    remove_tests: bool = typer.Option(
        True,
        "--remove-existing-tests/--keep-existing-tests",
        help="Remove original test sources and Git history before the agent starts",
    ),
    config_spec: list[str] = typer.Option([str(DEFAULT_CONFIG_FILE)], "-c", "--config"),
) -> None:
    raw = json.loads(dataset.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise typer.BadParameter("Dataset must be a JSON array")
    output_path = output or Path(f"testgen_results_{dataset.stem}_{int(time.time())}")
    output_path.mkdir(parents=True, exist_ok=True)
    result_path = output_dataset or output_path / f"{dataset.stem}_with_tests.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    results = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else raw
    if len(results) != len(raw):
        raise typer.BadParameter("Existing output dataset length does not match the input dataset")
    for result in results:
        result.pop("generated_test_files", None)
    write_results(result_path, results)
    add_file_handler(output_path / "minisweagent.log")

    instances = []
    for index, entry in enumerate(raw):
        instance = dict(entry)
        instance["_index"] = index
        instance["instance_id"] = make_instance_id(entry, index)
        instances.append(instance)
    instances = filter_instances(instances, filter_spec=filter_spec, slice_spec=slice_spec, shuffle=shuffle)
    if not redo_existing:
        instances = [instance for instance in instances if not is_completed_result(results[instance["_index"]])]

    configs = [get_config_from_spec(spec) for spec in config_spec]
    configs.append({"model": {"model_name": model or UNSET, "model_class": model_class or UNSET}})
    config = recursive_merge(*configs)
    progress_manager = RunBatchProgressManager(len(instances), output_path / f"exit_statuses_{int(time.time())}.yaml")

    def run(futures: dict[concurrent.futures.Future, str]) -> None:
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except concurrent.futures.CancelledError:
                pass
            except Exception as error:
                progress_manager.on_uncaught_exception(futures[future], error)

    with Live(progress_manager.render_group, refresh_per_second=4):
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    process_instance,
                    instance,
                    results,
                    result_path,
                    output_path,
                    config,
                    image,
                    infer_language(instance, language),
                    test_framework,
                    remove_tests,
                    progress_manager,
                ): instance["instance_id"]
                for instance in instances
            }
            try:
                run(futures)
            except KeyboardInterrupt:
                for future in futures:
                    future.cancel()
                run(futures)

    logger.info("Generated tests written to %s", result_path)


if __name__ == "__main__":
    app()
