#!/usr/bin/env python3
"""Prune manually curated dataset entries that are no longer externally accessible.

This deliberately takes the intersection of the existing curated dataset and
the current extractor output: it never adds newly discovered methods that have
not been reviewed or had a specification generated.
"""
import argparse
import contextlib
import io
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "extract_functions"))
from java_extra import JavaProjectTestScopeExtractor, discover_java_files
from py_extra import EnhancedPythonFocalExtractor, discover_python_files
from js_extra import JSProjectTestScopeExtractor, discover_javascript_files


def identity(entry):
    return (str(entry.get("src_file", "")), entry.get("start_line"),
            entry.get("end_line"), str(entry.get("name", "")))


def write_json_atomic(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def extract_accessible(language: str, project_root: Path, entries):
    """Re-parse only files already represented in the curated dataset."""
    files = sorted({
        str(project_root / str(entry["src_file"]))
        for entry in entries if entry.get("src_file")
        and (project_root / str(entry["src_file"])).is_file()
    })
    if language == "java":
        extractor = JavaProjectTestScopeExtractor(
            project_root=str(project_root), file_list=files)
    elif language == "python":
        extractor = EnhancedPythonFocalExtractor(
            project_root=str(project_root), file_list=files)
    else:
        extractor = JSProjectTestScopeExtractor(
            project_root=str(project_root), file_list=files,
            only_exported=True)
    # Extractors print one line per source file; dataset refresh should report
    # only the final project-level result.
    with contextlib.redirect_stdout(io.StringIO()):
        return extractor.extract_and_select_functions()


def refresh(path: Path) -> dict:
    language = path.parent.name
    if language not in {"java", "js", "python"}:
        raise ValueError(f"unsupported dataset language: {language}")
    entries = json.loads(path.read_text(encoding="utf-8"))
    roots = {entry.get("project_root") for entry in entries if entry.get("project_root")}
    if len(roots) != 1:
        raise ValueError(f"{path}: expected exactly one project_root, got {roots}")
    project_root = Path(next(iter(roots)))
    if not project_root.is_dir():
        raise FileNotFoundError(project_root)

    available = {identity(entry) for entry in extract_accessible(language, project_root, entries)}
    retained = [entry for entry in entries if identity(entry) in available]
    spec_path = path.with_name(path.stem + "_specification.json")
    write_json_atomic(path, retained)
    specifications = []
    retained_specs = []
    if spec_path.is_file():
        specifications = json.loads(spec_path.read_text(encoding="utf-8"))
        retained_ids = {identity(entry) for entry in retained}
        retained_specs = [entry for entry in specifications if identity(entry) in retained_ids]
        write_json_atomic(spec_path, retained_specs)
    return {
        "dataset": str(path.relative_to(ROOT)),
        "base_before": len(entries), "base_after": len(retained),
        "spec_before": len(specifications), "spec_after": len(retained_specs),
        "new_candidates_ignored": len(available - {identity(entry) for entry in entries}),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path,
                        help="base dataset JSON, e.g. dataset/java/parquet.json")
    args = parser.parse_args()
    path = args.dataset if args.dataset.is_absolute() else ROOT / args.dataset
    print(json.dumps(refresh(path), ensure_ascii=False))


if __name__ == "__main__":
    main()
