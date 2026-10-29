"""Select whole-project JSON files for a cross-language balanced benchmark."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import shutil
from pathlib import Path
from statistics import pstdev

from scipy.stats import wasserstein_distance


LANGUAGES = ("java", "python")
METRICS = ("loc", "complexity", "outgoing_degree")


def load_projects(dataset_dir: Path) -> dict[str, list[dict]]:
    result = {}
    for language in LANGUAGES:
        projects = []
        for path in sorted((dataset_dir / language).glob("*.json")):
            with path.open(encoding="utf-8") as handle:
                rows = json.load(handle)
            projects.append({"name": path.stem, "path": path, "rows": rows})
        result[language] = projects
    return result


def candidate_subsets(projects: list[dict], minimum: int, maximum: int) -> list[dict]:
    candidates = []
    for size in range(1, len(projects) + 1):
        for selected in itertools.combinations(projects, size):
            count = sum(len(project["rows"]) for project in selected)
            if minimum <= count <= maximum:
                rows = [row for project in selected for row in project["rows"]]
                candidates.append({
                    "projects": selected,
                    "rows": rows,
                    "count": count,
                    "values": {metric: [row[metric] for row in rows] for metric in METRICS},
                })
    return candidates


def select_pair(
    projects: dict[str, list[dict]], target: int, tolerance: int, equal_project_count: bool
) -> tuple[dict, dict, dict]:
    candidates = {
        language: candidate_subsets(items, target - tolerance, target + tolerance)
        for language, items in projects.items()
    }
    all_rows = [row for items in projects.values() for project in items for row in project["rows"]]
    scales = {metric: pstdev(row[metric] for row in all_rows) for metric in METRICS}
    best = None
    for java in candidates["java"]:
        for python in candidates["python"]:
            if equal_project_count and len(java["projects"]) != len(python["projects"]):
                continue
            distances = {
                metric: wasserstein_distance(java["values"][metric], python["values"][metric]) / scales[metric]
                for metric in METRICS
            }
            # Distribution match is primary. Small penalties prefer the target
            # size and equal language sizes when distribution quality is close.
            score = (
                sum(distances.values()) / len(METRICS)
                + 0.003 * (abs(java["count"] - target) + abs(python["count"] - target))
                + 0.002 * abs(java["count"] - python["count"])
            )
            result = (score, java, python, distances)
            if best is None or score < best[0]:
                best = result
    if best is None:
        raise ValueError("No project combination falls within the requested count range")
    return best[1], best[2], {"score": best[0], "normalized_wasserstein": best[3]}


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def write_outputs(output_dir: Path, selections: dict[str, dict], diagnostics: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    summaries = []
    for language, selection in selections.items():
        language_dir = output_dir / language
        language_dir.mkdir(parents=True, exist_ok=True)
        for project in selection["projects"]:
            destination = language_dir / project["path"].name
            shutil.copy2(project["path"], destination)
            manifest.append({
                "language": language,
                "project": project["name"],
                "function_count": len(project["rows"]),
                "source_json": str(project["path"]),
                "benchmark_json": str(destination),
            })
        for metric in METRICS:
            values = selection["values"][metric]
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
    for filename, rows in (("manifest.csv", manifest), ("summary.csv", summaries)):
        with (output_dir / filename).open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    with (output_dir / "selection_diagnostics.json").open("w", encoding="utf-8") as handle:
        json.dump(diagnostics, handle, indent=2, ensure_ascii=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", type=Path, default=Path("dataset"))
    parser.add_argument("--output-dir", type=Path, default=Path("dataset/benchmark_balanced_200"))
    parser.add_argument("--target", type=int, default=200)
    parser.add_argument("--tolerance", type=int, default=10)
    parser.add_argument(
        "--equal-project-count", action="store_true",
        help="Require Java and Python to contain the same number of projects",
    )
    args = parser.parse_args()
    projects = load_projects(args.dataset_dir)
    java, python, diagnostics = select_pair(
        projects, args.target, args.tolerance, args.equal_project_count
    )
    selections = {"java": java, "python": python}
    diagnostics.update({
        "target": args.target,
        "tolerance": args.tolerance,
        "equal_project_count": args.equal_project_count,
        "function_counts": {language: selection["count"] for language, selection in selections.items()},
        "projects": {
            language: [project["name"] for project in selection["projects"]]
            for language, selection in selections.items()
        },
    })
    write_outputs(args.output_dir, selections, diagnostics)
    print(json.dumps(diagnostics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
