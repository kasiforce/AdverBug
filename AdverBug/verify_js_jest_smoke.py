"""Verify that every source module in whole-project JS JSONs loads in isolated Jest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from screen_js_repo import detect_build, run_import_smoke, setup_deps


def verify(project_dir: Path, dataset_json: Path, install_timeout: int, timeout: int) -> dict:
    records = json.loads(dataset_json.read_text(encoding="utf-8"))
    source_files = sorted({record["src_file"] for record in records})
    build = detect_build(str(project_dir))
    if build is None:
        return {"ok": False, "reason": "root package.json missing"}
    ok, reason = setup_deps(str(project_dir), build["lockfile_mgr"], install_timeout)
    if not ok:
        return {"ok": False, "reason": reason}
    smoke = run_import_smoke(str(project_dir), source_files, timeout)
    failed = sorted(set(source_files) - smoke.get("loadable", set()))
    return {
        "ok": smoke["ok"] and not failed,
        "function_count": len(records),
        "source_file_count": len(source_files),
        "loadable_file_count": len(smoke.get("loadable", set())),
        "failed_files": failed,
        "seconds": smoke.get("seconds"),
        "native_jest_declared": build["jest_declared"],
        "reason": smoke.get("reason", "") if smoke["ok"] else smoke.get("reason", ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec", nargs="+", help="name=dataset-json (project is projects/name)")
    parser.add_argument("--projects-dir", type=Path, default=Path("projects"))
    parser.add_argument("--output", type=Path, default=Path("dataset/js_expansion_candidates/jest_smoke.json"))
    parser.add_argument("--install-timeout", type=int, default=1800)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    results = {}
    for spec in args.spec:
        name, json_path = spec.split("=", 1)
        print(f"[{name}] installing dependencies and running isolated Jest import smoke...", flush=True)
        try:
            result = verify(args.projects_dir / name, Path(json_path), args.install_timeout, args.timeout)
        except Exception as exc:
            result = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
        results[name] = result
        print(json.dumps({name: result}, ensure_ascii=False), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
