#!/usr/bin/env python3

"""Verify that benchmark images can run a newly added test after original tests are removed."""

import argparse
import concurrent.futures
import json
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from minisweagent.run.benchmarks.testgen import (
    build_test_artifact_find_command,
    build_test_file_find_command,
)

JUNIT5_SMOKE = """import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertTrue;

class BenchmarkSmokeTest {
    @Test
    void environmentWorks() {
        assertTrue(true);
    }
}
"""

JUNIT4_SMOKE = """import org.junit.Test;
import static org.junit.Assert.assertTrue;

public class BenchmarkSmokeTest {
    @Test
    public void environmentWorks() {
        assertTrue(true);
    }
}
"""

TESTNG_SMOKE = """import org.testng.annotations.Test;
import static org.testng.Assert.assertTrue;

public class BenchmarkSmokeTest {
    @Test
    public void environmentWorks() {
        assertTrue(true);
    }
}
"""


@dataclass(frozen=True)
class Project:
    image: str
    language: str
    test_path: str
    test_source: str
    test_command: str


CONDA = "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && "
PROJECTS = {
    "parser": Project(
        "adver-jsqlparser:test",
        "java",
        "src/test/java/BenchmarkSmokeTest.java",
        JUNIT5_SMOKE,
        "mvn -B -ntp -Dtest=BenchmarkSmokeTest test",
    ),
    "prone": Project(
        "adver-prone:test",
        "java",
        "check_api/src/test/java/BenchmarkSmokeTest.java",
        JUNIT4_SMOKE,
        "mvn -B -ntp -pl check_api -am -Dtest=BenchmarkSmokeTest "
        "-Dsurefire.failIfNoSpecifiedTests=false test",
    ),
    "fory": Project(
        "adver-fory:test",
        "java",
        "java/fory-core/src/test/java/BenchmarkSmokeTest.java",
        TESTNG_SMOKE,
        "cd /testbed/java && mvn -B -ntp -pl fory-core -am -Dtest=BenchmarkSmokeTest "
        "-Dsurefire.failIfNoSpecifiedTests=false test",
    ),
    "graphql": Project(
        "adver-graphql:test",
        "java",
        "src/test/java/BenchmarkSmokeTest.java",
        JUNIT5_SMOKE,
        "./gradlew --no-daemon test --tests BenchmarkSmokeTest",
    ),
    "leaf": Project(
        "adver-thymeleaf:test",
        "java",
        "tests/thymeleaf-tests-core/src/test/java/BenchmarkSmokeTest.java",
        JUNIT5_SMOKE,
        "mvn -B -ntp -pl tests/thymeleaf-tests-core -am -Dtest=BenchmarkSmokeTest "
        "-Dsurefire.failIfNoSpecifiedTests=false test",
    ),
    "pdfbox": Project(
        "adver-pdfbox:test",
        "java",
        "debugger/src/test/java/BenchmarkSmokeTest.java",
        JUNIT5_SMOKE,
        "attempt=1; until mvn -B -ntp -f debugger/pom.xml -Dtest=BenchmarkSmokeTest "
        "-Dsurefire.failIfNoSpecifiedTests=false test; do "
        '[ "$attempt" -ge 10 ] && exit 1; attempt=$((attempt + 1)); done',
    ),
    "darts": Project(
        "adverbug-python-darts:loc100",
        "python",
        "tests/generated/test_benchmark_smoke.py",
        "def test_environment():\n    import darts.ad.utils\n",
        "python -m pytest -q tests/generated/test_benchmark_smoke.py",
    ),
    "dowhy": Project(
        "adverbug-python-dowhy:loc100",
        "python",
        "tests/generated/test_benchmark_smoke.py",
        "def test_environment():\n    import dowhy\n",
        f"{CONDA}python -m pytest -q tests/generated/test_benchmark_smoke.py",
    ),
    "scikit": Project(
        "adverbug-python-scikit:loc100",
        "python",
        "tests/generated/test_benchmark_smoke.py",
        "def test_environment():\n    import sklearn\n",
        f"{CONDA}python -m pytest -q tests/generated/test_benchmark_smoke.py",
    ),
    "sqlglot": Project(
        "adver-sqlglot:test",
        "python",
        "tests/generated/test_benchmark_smoke.py",
        "def test_environment():\n    import sqlglot\n",
        f"{CONDA}python -m pytest -q tests/generated/test_benchmark_smoke.py",
    ),
}


def run(command: list[str], *, timeout: int = 1200, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, capture_output=True, text=True, timeout=timeout)


def docker_exec(container: str, command: str, *, timeout: int = 1200) -> subprocess.CompletedProcess[str]:
    return run(["docker", "exec", container, "bash", "-lc", command], timeout=timeout, check=False)


def verify(name: str, project: Project) -> dict:
    container = f"test-isolation-{name}-{uuid.uuid4().hex[:8]}"
    result = {"project": name, "image": project.image, "passed": False}
    try:
        run(["docker", "run", "-d", "--rm", "--name", container, "-w", "/testbed", project.image, "sleep", "30m"])
        listing = docker_exec(container, build_test_file_find_command(project.language))
        if listing.returncode != 0:
            raise RuntimeError(listing.stdout + listing.stderr)
        removed = [line for line in listing.stdout.splitlines() if line.strip()]
        deletion = docker_exec(container, build_test_file_find_command(project.language, delete=True))
        if deletion.returncode != 0:
            raise RuntimeError(deletion.stdout + deletion.stderr)
        artifact_cleanup = docker_exec(container, build_test_artifact_find_command(delete=True))
        if artifact_cleanup.returncode != 0:
            raise RuntimeError(artifact_cleanup.stdout + artifact_cleanup.stderr)
        remaining_sources = docker_exec(container, build_test_file_find_command(project.language))
        remaining_artifacts = docker_exec(container, build_test_artifact_find_command())
        if remaining_sources.returncode != 0 or remaining_sources.stdout.strip():
            raise RuntimeError(f"test sources remain after deletion: {remaining_sources.stdout}")
        if remaining_artifacts.returncode != 0 or remaining_artifacts.stdout.strip():
            raise RuntimeError(f"test artifacts remain after deletion: {remaining_artifacts.stdout}")
        sanitized = docker_exec(
            container,
            "rm -rf /testbed/.git && git init -q /testbed && "
            "git -C /testbed config user.name benchmark && "
            "git -C /testbed config user.email benchmark@localhost && "
            "git -C /testbed add -A && "
            "git -C /testbed -c core.hooksPath=/dev/null commit -q --no-gpg-sign -m sanitized-baseline",
        )
        if sanitized.returncode != 0:
            raise RuntimeError(sanitized.stdout + sanitized.stderr)

        docker_exec(container, f"mkdir -p {str(Path('/testbed') / Path(project.test_path).parent)}")
        with tempfile.TemporaryDirectory() as temp_dir:
            smoke = Path(temp_dir) / Path(project.test_path).name
            smoke.write_text(project.test_source, encoding="utf-8")
            run(["docker", "cp", str(smoke), f"{container}:/testbed/{project.test_path}"])

        test = docker_exec(container, project.test_command)
        result.update(
            {
                "passed": test.returncode == 0,
                "removed_test_file_count": len(removed),
                "returncode": test.returncode,
                "output_tail": (test.stdout + test.stderr)[-4000:],
            }
        )
    except Exception as error:
        result["error"] = str(error)
    finally:
        run(["docker", "stop", "-t", "1", container], timeout=30, check=False)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("projects", nargs="*", metavar="PROJECT")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    selected = args.projects or sorted(PROJECTS)
    unknown = sorted(set(selected) - PROJECTS.keys())
    if unknown:
        parser.error(f"unknown projects: {', '.join(unknown)}; choose from {', '.join(sorted(PROJECTS))}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        results = list(executor.map(lambda name: verify(name, PROJECTS[name]), selected))
    report = json.dumps(results, indent=2, ensure_ascii=False)
    print(report)
    if args.output:
        args.output.write_text(report + "\n", encoding="utf-8")
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
