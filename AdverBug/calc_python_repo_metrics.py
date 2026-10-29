"""Calculate production-Python file metrics and apply P50 filtering.

The source metrics exclude common test, documentation, example, build, and
virtual-environment directories. ``source_loc`` counts non-empty, non-comment
physical lines in the remaining Python files.
"""

import argparse
import csv
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import median

EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "env", "build", "dist", "vendor",
    "generated", "docs", "doc", "examples", "example", "samples",
    "tests", "test", "testing", "benchmarks", "scripts",
}


def run(cmd, cwd=None, timeout=300):
    return subprocess.run(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, timeout=timeout, check=False,
    )


def is_source_py(rel_path):
    parts = rel_path.replace(os.sep, "/").split("/")
    lowered = [part.lower() for part in parts]
    base = lowered[-1]
    if any(part in EXCLUDE_DIRS for part in lowered[:-1]):
        return False
    if not base.endswith(".py") or base in {"setup.py", "conftest.py"}:
        return False
    return not (base.startswith("test_") or base.endswith("_test.py"))


def count_source_lines(path):
    count = 0
    with open(path, encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                count += 1
    return count


def clone_and_measure(repo, work_root):
    full_name = repo["full_name"]
    branch = repo.get("default_branch") or ""
    target = os.path.join(work_root, full_name.replace("/", "__"))
    url = f"https://github.com/{full_name}.git"
    try:
        proc = run([
            "git", "clone", "--quiet", "--depth=1", "--filter=blob:none",
            "--no-checkout", url, target,
        ], timeout=600)
        if proc.returncode != 0:
            # Some GitHub mirrors do not support partial clone filtering.
            shutil.rmtree(target, ignore_errors=True)
            proc = run([
                "git", "clone", "--quiet", "--depth=1", "--no-checkout",
                url, target,
            ], timeout=600)
        if proc.returncode != 0:
            return repo, {"metric_status": "clone_failed"}

        # Only check out Python files. This avoids downloading README/media and
        # most non-Python blobs when the server supports partial clone.
        for cmd in (
            ["git", "sparse-checkout", "init", "--no-cone"],
            ["git", "sparse-checkout", "set", "--no-cone", "/*.py", "**/*.py"],
            ["git", "checkout", "--quiet", "HEAD"],
        ):
            proc = run(cmd, cwd=target, timeout=600)
            if proc.returncode != 0:
                return repo, {"metric_status": "checkout_failed"}

        lengths = []
        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d.lower() not in EXCLUDE_DIRS]
            for filename in files:
                path = os.path.join(root, filename)
                rel = os.path.relpath(path, target)
                if is_source_py(rel):
                    lengths.append(count_source_lines(path))

        if not lengths:
            return repo, {"metric_status": "no_source"}
        return repo, {
            "metric_status": "ok",
            "source_file_count": len(lengths),
            "source_loc": sum(lengths),
            "avg_file_loc": sum(lengths) / len(lengths),
            "median_file_loc": median(lengths),
            "p90_file_loc": sorted(lengths)[max(0, int(0.9 * len(lengths)) - 1)],
            "max_file_loc": max(lengths),
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return repo, {"metric_status": f"error:{type(exc).__name__}"}
    finally:
        shutil.rmtree(target, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="AdverBug/github_repos_python.csv")
    parser.add_argument("--metrics-output", default="AdverBug/github_repos_python_metrics.csv")
    parser.add_argument("--filtered-output", default="AdverBug/github_repos_python_p50.csv")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    with open(args.input, newline="", encoding="utf-8") as handle:
        repos = list(csv.DictReader(handle))
    if not repos:
        raise SystemExit("candidate CSV is empty")

    work_root = tempfile.mkdtemp(prefix="python-repo-metrics-")
    results = {}
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(clone_and_measure, repo, work_root) for repo in repos]
            for index, future in enumerate(as_completed(futures), 1):
                repo, metrics = future.result()
                results[repo["full_name"]] = metrics
                print(f"[{index}/{len(repos)}] {repo['full_name']}: {metrics.get('metric_status')}", flush=True)
    finally:
        shutil.rmtree(work_root, ignore_errors=True)

    successful = [m for m in results.values() if m.get("metric_status") == "ok"]
    if not successful:
        raise SystemExit("no repositories produced usable source metrics")
    thresholds = {
        "source_file_count": median(m["source_file_count"] for m in successful),
        "source_loc": median(m["source_loc"] for m in successful),
        "median_file_loc": median(m["median_file_loc"] for m in successful),
    }
    print("P50 thresholds:", thresholds)

    fieldnames = list(repos[0].keys()) + [
        "metric_status", "source_file_count", "source_loc", "avg_file_loc",
        "median_file_loc", "p90_file_loc", "max_file_loc", "p50_selected",
    ]
    rows = []
    selected = []
    for repo in repos:
        metrics = results[repo["full_name"]]
        row = dict(repo)
        row.update(metrics)
        is_selected = metrics.get("metric_status") == "ok" and all(
            metrics[key] >= threshold for key, threshold in thresholds.items()
        )
        row["p50_selected"] = is_selected
        rows.append(row)
        if is_selected:
            selected.append(row)

    for output, output_rows in ((args.metrics_output, rows), (args.filtered_output, selected)):
        with open(output, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(output_rows)

    print(f"usable={len(successful)}, selected={len(selected)}, total={len(repos)}")
    print(f"metrics written to {args.metrics_output}")
    print(f"P50-filtered repositories written to {args.filtered_output}")


if __name__ == "__main__":
    main()
