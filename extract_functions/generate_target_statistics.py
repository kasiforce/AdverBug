#!/usr/bin/env python3
"""Generate reproducible CSV/JSON/PNG summaries for file or module targets."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any


LANGUAGES = (
    ("java", "Java"),
    ("python", "Python"),
    ("js", "JavaScript"),
)
STATISTICS = (
    ("Mean", lambda values: sum(values) / len(values)),
    ("Min", min),
    ("Q1", lambda values: percentile(values, 0.25)),
    ("Median", lambda values: percentile(values, 0.50)),
    ("Q3", lambda values: percentile(values, 0.75)),
    ("Max", max),
)


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def load_records(dataset: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, list[dict[str, Any]]]]]:
    by_language: dict[str, list[dict[str, Any]]] = {}
    by_project: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for directory, label in LANGUAGES:
        language_records: list[dict[str, Any]] = []
        projects: dict[str, list[dict[str, Any]]] = {}
        for path in sorted((dataset / directory).glob("*.json")):
            records = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(records, list):
                raise ValueError(f"Expected a JSON array in {path}")
            projects[path.stem] = records
            language_records.extend(records)
        by_language[label] = language_records
        by_project[label] = projects
    return by_language, by_project


def write_metric_statistics(
    path: Path,
    by_language: dict[str, list[dict[str, Any]]],
    metrics: tuple[tuple[str, str], ...],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Metric", "Statistic", "Java", "Python", "JavaScript", "Total"])
        for metric, field in metrics:
            values_by_language = {
                language: [float(record.get(field, 0)) for record in records]
                for language, records in by_language.items()
            }
            combined = sum(values_by_language.values(), [])
            for statistic, function in STATISTICS:
                row = [metric, statistic]
                for language in ("Java", "Python", "JavaScript"):
                    values = values_by_language[language]
                    row.append(function(values) if values else "")
                row.append(function(combined) if combined else "")
                writer.writerow(row)


def distribution_count(values: list[float], lower: float, upper: float | None) -> int:
    return sum(value >= lower and (upper is None or value < upper) for value in values)


def write_distribution(
    path: Path,
    by_language: dict[str, list[dict[str, Any]]],
    bins: tuple[tuple[str, float, float | None], ...],
) -> dict[str, list[int]]:
    counts: dict[str, list[int]] = {language: [] for language in by_language}
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["NLOC Range", "Statistic", "Java", "Python", "JavaScript", "Total"])
        totals = {language: len(records) for language, records in by_language.items()}
        grand_total = sum(totals.values())
        for label, lower, upper in bins:
            row_counts = []
            for language in ("Java", "Python", "JavaScript"):
                values = [float(record["nloc"]) for record in by_language[language]]
                count = distribution_count(values, lower, upper)
                counts[language].append(count)
                row_counts.append(count)
            total = sum(row_counts)
            writer.writerow([label, "Count", *row_counts, total])
            writer.writerow(
                [
                    label,
                    "Percentage",
                    *(count / totals[language] * 100 if totals[language] else 0 for count, language in zip(row_counts, ("Java", "Python", "JavaScript"))),
                    total / grand_total * 100 if grand_total else 0,
                ]
            )
    return counts


def write_plot(
    path: Path,
    bins: tuple[tuple[str, float, float | None], ...],
    counts: dict[str, list[int]],
    title: str,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    languages = ("Java", "Python", "JavaScript", "Total")
    totals_by_bin = [
        sum(counts[language][index] for language in languages[:-1])
        for index in range(len(bins))
    ]
    raw_counts = {
        **counts,
        "Total": totals_by_bin,
    }
    percentages = {
        language: [
            count / sum(raw_counts[language]) * 100 if sum(raw_counts[language]) else 0
            for count in raw_counts[language]
        ]
        for language in languages
    }
    colors = ("#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2", "#B279A2")
    bottom = [0.0] * len(languages)
    figure, axis = plt.subplots(figsize=(12, 7))
    for index, (label, _, _) in enumerate(bins):
        heights = [percentages[language][index] for language in languages]
        bars = axis.bar(
            languages,
            heights,
            bottom=bottom,
            label=f"{label} NLOC",
            color=colors[index],
        )
        for bar, height, base in zip(bars, heights, bottom):
            if height <= 0:
                continue
            axis.text(
                bar.get_x() + bar.get_width() / 2,
                base + height / 2,
                f"{height:.1f}%",
                ha="center",
                va="center",
                fontsize=10,
                fontweight="bold",
                color="white" if index in (0, 3, 5) else "black",
            )
        bottom = [base + height for base, height in zip(bottom, heights)]
    axis.set_xlabel("Language / Overall")
    axis.set_ylabel("Percentage (%)")
    axis.set_title(title)
    axis.set_ylim(0, 105)
    axis.grid(axis="y", linestyle="--", alpha=0.35)
    axis.set_axisbelow(True)
    axis.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3)
    figure.tight_layout(rect=(0, 0.08, 1, 1))
    figure.savefig(path, dpi=180)
    plt.close(figure)


def project_universe(root: Path | None) -> dict[str, set[str]]:
    universe = {label: set() for _, label in LANGUAGES}
    if root is None:
        return universe
    for directory, label in LANGUAGES:
        universe[label] = {
            path.stem
            for path in (root / directory).glob("*.json")
            if not path.stem.endswith("_specification")
        }
    return universe


def write_project_counts(
    path: Path,
    kind: str,
    by_project: dict[str, dict[str, list[dict[str, Any]]]],
    universe: dict[str, set[str]],
) -> None:
    unit = "File" if kind == "file" else "Module"
    primary_source = "target_function_file" if kind == "file" else "target_function_module"
    fallback_source = "project_fallback"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "Language",
                "Project",
                f"Selected {unit} Count",
                f"Target Function {unit} Count",
                f"Fallback {unit} Count",
                "LOC >= 100 Target Count",
            ]
        )
        for language in ("Java", "Python", "JavaScript"):
            projects = set(by_project[language]) | universe[language]
            for project in sorted(projects):
                records = by_project[language].get(project, [])
                writer.writerow(
                    [
                        language,
                        project,
                        len(records),
                        sum(record.get("selection_source") == primary_source for record in records),
                        sum(record.get("selection_source") == fallback_source for record in records),
                        sum(int(record.get("loc_ge_100_target_count", 0)) for record in records),
                    ]
                )


def selection_criteria(
    kind: str,
    fallback_primary_count_below: int = 1,
    min_cross_file_internal_method_fanout: int = 0,
    min_resolved_cross_file_internal_method_fanout: int = 0,
) -> dict[str, Any]:
    callable_definition = {
        "minimum": 1,
        "definition": (
            "Non-empty, non-abstract test entries: Python public-by-naming-convention "
            "functions/methods; JavaScript exported functions and public methods of exported "
            "classes; Java non-private concrete methods in non-private classes."
        ),
    }
    if kind == "file":
        fallback_selection = (
            "If a project has no primary file, use all size-eligible files."
            if fallback_primary_count_below <= 1
            else (
                "If a project has fewer than "
                f"{fallback_primary_count_below} primary files, retain them and supplement "
                "with all other size-eligible files."
            )
        )
        return {
            "target_type": "source_file",
            "min_nloc": 300,
            "min_concrete_method_count": 3,
            "min_total_cyclomatic_complexity": 50,
            "min_cross_file_internal_method_fanout": (
                min_cross_file_internal_method_fanout
            ),
            "min_resolved_cross_file_internal_method_fanout": (
                min_resolved_cross_file_internal_method_fanout
            ),
            "min_callable_entry_count": callable_definition,
            "primary_selection": "Eligible files containing a loc_ge_100 target function.",
            "fallback_selection": fallback_selection,
            "excluded_paths": ["packages/imba/src/compiler/nodes.mjs"],
        }
    return {
        "target_type": "module",
        "module_scope": "recursive_directory",
        "production_file_count": {"min": 3, "max": 10},
        "min_total_nloc": 500,
        "min_callable_entry_count": callable_definition,
        "primary_selection": "Eligible modules containing a loc_ge_100 target function.",
        "fallback_selection": "If a project has no primary module, use all size-eligible modules.",
        "overlap_resolution": "For overlapping parent/child candidates, retain deeper non-overlapping modules.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--kind", required=True, choices=("file", "module"))
    parser.add_argument("--project-universe", type=Path)
    parser.add_argument("--fallback-primary-count-below", type=int, default=1)
    parser.add_argument("--min-cross-file-internal-method-fanout", type=int, default=0)
    parser.add_argument(
        "--min-resolved-cross-file-internal-method-fanout", type=int, default=0
    )
    args = parser.parse_args()

    by_language, by_project = load_records(args.dataset)
    output = args.dataset / "statistics"
    output.mkdir(parents=True, exist_ok=False)

    common_metrics = (
        ("NLOC", "nloc"),
        ("Cyclomatic Complexity", "total_cyclomatic_complexity"),
        ("Concrete Method Count", "concrete_method_count"),
        ("Callable Entry Count", "callable_entry_count"),
        ("LOC >= 100 Target Count", "loc_ge_100_target_count"),
    )
    if args.kind == "file":
        metrics = common_metrics + (
            ("Average Function Cyclomatic Complexity", "average_function_cyclomatic_complexity"),
            ("Cross-file Internal Method Fanout", "cross_file_internal_method_fanout"),
            (
                "Resolved Cross-file Internal Method Fanout",
                "resolved_cross_file_internal_method_fanout",
            ),
        )
        bins = (("[300-500)", 300, 500), ("[500-750)", 500, 750), ("[750-1000)", 750, 1000), ("[1000-1500)", 1000, 1500), ("[1500+)", 1500, None))
        metric_name = "file_statistics.csv"
        count_name = "project_file_counts.csv"
        title = "File-level Target NLOC Distribution"
    else:
        metrics = common_metrics + (("File Count", "file_count"),)
        bins = (("[500-750)", 500, 750), ("[750-1000)", 750, 1000), ("[1000-1500)", 1000, 1500), ("[1500-2000)", 1500, 2000), ("[2000-3000)", 2000, 3000), ("[3000+)", 3000, None))
        metric_name = "module_statistics.csv"
        count_name = "project_module_counts.csv"
        title = "Module-level Target NLOC Distribution"

    write_metric_statistics(output / metric_name, by_language, metrics)
    counts = write_distribution(output / "nloc_distribution.csv", by_language, bins)
    write_plot(output / "nloc_distribution_stacked_bar.png", bins, counts, title)
    write_project_counts(
        output / count_name,
        args.kind,
        by_project,
        project_universe(args.project_universe),
    )
    (output / "selection_criteria.json").write_text(
        json.dumps(
            selection_criteria(
                args.kind,
                args.fallback_primary_count_below,
                args.min_cross_file_internal_method_fanout,
                args.min_resolved_cross_file_internal_method_fanout,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote statistics for {sum(map(len, by_language.values()))} targets to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
