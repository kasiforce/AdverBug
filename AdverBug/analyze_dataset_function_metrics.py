"""Summarize and plot function metrics stored in language subdirectories.

The dataset JSON files already contain metrics computed during function
extraction.  This script deliberately consumes those values rather than
re-parsing source code, so its results use exactly the dataset's selection and
measurement conventions.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from statistics import mean, median, stdev


METRICS = ("loc", "complexity", "outgoing_degree")
LANGUAGES = ("java", "python", "js")
LANGUAGE_LABELS = {"java": "Java", "python": "Python", "js": "JavaScript"}
METRIC_LABELS = {
    "loc": "Function LOC (NLOC)",
    "complexity": "Cyclomatic complexity",
    "outgoing_degree": "Call out-degree",
}


def percentile(values: list[float], probability: float) -> float:
    """Return the NumPy-compatible linear-interpolation percentile."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)


def describe(values: list[float]) -> dict[str, float | int]:
    q1 = percentile(values, 0.25)
    q3 = percentile(values, 0.75)
    iqr = q3 - q1
    low_fence = q1 - 1.5 * iqr
    high_fence = q3 + 1.5 * iqr
    non_outliers = [value for value in values if low_fence <= value <= high_fence]
    return {
        "count": len(values),
        "mean": mean(values),
        "std": stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "q1": q1,
        "median": median(values),
        "q3": q3,
        "max": max(values),
        "iqr": iqr,
        "lower_whisker": min(non_outliers),
        "upper_whisker": max(non_outliers),
        "outlier_count": len(values) - len(non_outliers),
    }


def load_dataset(dataset_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for language in LANGUAGES:
        for json_path in sorted((dataset_dir / language).glob("*.json")):
            with json_path.open(encoding="utf-8") as handle:
                records = json.load(handle)
            if not isinstance(records, list):
                raise ValueError(f"Expected a JSON list in {json_path}")
            for index, record in enumerate(records):
                missing = [metric for metric in METRICS if not isinstance(record.get(metric), (int, float))]
                if missing:
                    raise ValueError(f"Missing/non-numeric {missing} in {json_path}, item {index}")
                rows.append({
                    "language": language,
                    "project": json_path.stem,
                    "dataset_file": str(json_path),
                    "src_file": record.get("src_file", ""),
                    "test_file": record.get("test_file", ""),
                    "function_name": record.get("name", ""),
                    "method_key": record.get("method_key", ""),
                    **{metric: record[metric] for metric in METRICS},
                })
    return rows


def summary_rows(rows: list[dict], group_keys: tuple[str, ...]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        key = tuple(row[field] for field in group_keys)
        groups.setdefault(key, []).append(row)
    output = []
    for key, group in sorted(groups.items()):
        for metric in METRICS:
            result = dict(zip(group_keys, key))
            result["metric"] = metric
            result.update(describe([row[metric] for row in group]))
            output.append(result)
    return output


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def make_plots(rows: list[dict], output_dir: Path) -> None:
    # Avoid failures when the user's default matplotlib cache is read-only.
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/adver_bug_matplotlib")
    import matplotlib.pyplot as plt

    languages = tuple(language for language in LANGUAGES if any(
        row["language"] == language for row in rows
    ))
    colors = ("#4C78A8", "#F58518", "#54A24B")
    figure, axes = plt.subplots(1, 3, figsize=(13, 4.8))
    for axis, metric in zip(axes, METRICS):
        values = [[row[metric] for row in rows if row["language"] == language] for language in languages]
        boxes = axis.boxplot(
            values,
            tick_labels=[LANGUAGE_LABELS[name] for name in languages],
            patch_artist=True,
        )
        for patch, color in zip(boxes["boxes"], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.75)
        axis.set_title(METRIC_LABELS[metric])
        axis.set_ylabel("Value")
        axis.grid(axis="y", alpha=0.25)
    figure.suptitle("Tested-function metrics by language")
    figure.tight_layout()
    for suffix in ("png", "pdf"):
        figure.savefig(output_dir / f"boxplots_by_language.{suffix}", dpi=220, bbox_inches="tight")
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", type=Path, default=Path("dataset"))
    parser.add_argument("--output-dir", type=Path, default=Path("dataset/function_metrics_stats"))
    args = parser.parse_args()

    rows = load_dataset(args.dataset_dir)
    if not rows:
        raise SystemExit("No Java/Python dataset records found")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "function_metrics_detail.csv", rows)
    write_csv(args.output_dir / "summary_by_language.csv", summary_rows(rows, ("language",)))
    write_csv(args.output_dir / "summary_by_project.csv", summary_rows(rows, ("language", "project")))
    make_plots(rows, args.output_dir)
    print(f"Analyzed {len(rows)} functions; outputs written to {args.output_dir}")


if __name__ == "__main__":
    main()
