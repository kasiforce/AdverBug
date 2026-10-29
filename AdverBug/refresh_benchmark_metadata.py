#!/usr/bin/env python3
"""Refresh metadata for an already materialized multi-language benchmark."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import median

from scipy.stats import wasserstein_distance


LANGUAGES = ("java", "python", "js")
METRICS = ("loc", "complexity", "outgoing_degree")


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--benchmark-dir", type=Path,
        default=Path("dataset/benchmark_balanced_200_call_degree"),
    )
    args = parser.parse_args()
    root = args.benchmark_dir

    old_sources: dict[tuple[str, str], str] = {}
    manifest_path = root / "manifest.csv"
    if manifest_path.exists():
        with manifest_path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                old_sources[(row["language"], row["project"])] = row["source_json"]
    old_sources.setdefault(("js", "imba"), "dataset/js_expansion_candidates/imba.json")

    by_language: dict[str, list[dict]] = {}
    projects: dict[str, list[str]] = {}
    manifest = []
    for language in LANGUAGES:
        combined = []
        projects[language] = []
        for path in sorted((root / language).glob("*.json")):
            rows = json.loads(path.read_text(encoding="utf-8"))
            combined.extend(rows)
            projects[language].append(path.stem)
            manifest.append({
                "language": language,
                "project": path.stem,
                "function_count": len(rows),
                "source_json": old_sources.get((language, path.stem), ""),
                "benchmark_json": str(path),
            })
        by_language[language] = combined

    summaries = []
    for language in LANGUAGES:
        for metric in METRICS:
            values = [row[metric] for row in by_language[language]]
            summaries.append({
                "language": language,
                "metric": metric,
                "count": len(values),
                "mean": sum(values) / len(values),
                "min": min(values),
                "q1": percentile(values, 0.25),
                "median": percentile(values, 0.5),
                "q3": percentile(values, 0.75),
                "max": max(values),
            })
    write_csv(manifest_path, manifest)
    write_csv(root / "summary.csv", summaries)

    diagnostics_path = root / "selection_diagnostics.json"
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    counts = {language: len(rows) for language, rows in by_language.items()}
    diagnostics["function_counts"] = counts
    diagnostics["projects"] = projects
    diagnostics["selection_policy"]["project_counts"] = {
        language: len(names) for language, names in projects.items()
    }
    diagnostics["selection_policy"].pop("project_count_per_language", None)
    removal_log_path = root / "suitability" / "removed_functions.json"
    removed_count = 0
    if removal_log_path.exists():
        removed_count = json.loads(
            removal_log_path.read_text(encoding="utf-8")
        ).get("removed_count", 0)
    diagnostics["selection_policy"]["post_selection_suitability_filter"] = (
        f"{removed_count} excluded or invalid-metric functions removed; "
        "review functions retained"
    )
    distances = {}
    pairs = (("java", "python"), ("java", "js"), ("python", "js"))
    for metric in METRICS:
        values = {
            language: [row[metric] for row in rows]
            for language, rows in by_language.items()
        }
        scale = median(value for group in values.values() for value in group)
        pairwise = {
            f"{left}_vs_{right}": wasserstein_distance(values[left], values[right]) / scale
            for left, right in pairs
        }
        distances[metric] = {
            "normalization_median": scale,
            "normalized_wasserstein": pairwise,
            "pairwise_mean": sum(pairwise.values()) / len(pairwise),
        }
    diagnostics["distribution_distance"] = distances
    smoke_path = root / "js_jest_smoke.json"
    if smoke_path.exists():
        smoke_results = json.loads(smoke_path.read_text(encoding="utf-8"))
        diagnostics["js_smoke"] = {
            project: (
                f"passed {result.get('loadable_file_count', 0)}/"
                f"{result.get('source_file_count', 0)} source modules"
                if result.get("ok") else f"failed: {result.get('reason', '')}"
            )
            for project, result in smoke_results.items()
        }
    diagnostics_path.write_text(
        json.dumps(diagnostics, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"function_counts": counts, "projects": projects}, indent=2))


if __name__ == "__main__":
    main()
