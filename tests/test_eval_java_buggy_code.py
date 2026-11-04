from __future__ import annotations

import sys
from pathlib import Path


EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"
sys.path.insert(0, str(EVAL_DIR))

from eval_java import _stage_item, attach_bug_patches  # noqa: E402


def _test_item(**overrides: object) -> dict:
    item = {
        "name": "read",
        "method_key": "read(int index)",
        "start_line": 42,
        "src_file": "module/src/main/java/example/Reader.java",
        "test_file": "module/src/test/java/example/ReaderTests.java",
        "generated_tests": ["class ReaderTests {}"],
        "mini_swe_agent": {"instance_id": "example__read__42"},
    }
    item.update(overrides)
    return item


def _bug_item(**overrides: object) -> dict:
    item = {
        "name": "read",
        "method_key": "read(int index)",
        "start_line": 42,
        "src_file": "module/src/main/java/example/Reader.java",
        "code": "int read(int index) { return index; }",
        "buggy_code": ["int read(int index) { return -index; }"],
        "bug_summary": "negates the result",
    }
    item.update(overrides)
    return item


def test_attach_bug_patches_matches_signature_and_skips_unmatched() -> None:
    unmatched_test = _test_item(
        name="write",
        method_key="write(int value)",
        src_file="module/src/main/java/example/Writer.java",
    )

    matched, unmatched = attach_bug_patches(
        [_test_item(), unmatched_test], [_bug_item()]
    )

    assert len(matched) == 1
    assert matched[0]["evaluation_code_variant"] == "buggy"
    assert matched[0]["bug_patch"]["buggy_code"] == "int read(int index) { return -index; }"
    assert unmatched == [
        {
            "instance_id": "example__read__42",
            "name": "write",
            "method_key": "write(int value)",
            "src_file": "module/src/main/java/example/Writer.java",
            "reason": "no_matching_bug",
        }
    ]


def test_attach_bug_patches_uses_last_nonempty_bug() -> None:
    matched, _ = attach_bug_patches(
        [_test_item()],
        [_bug_item(buggy_code=["first mutation", "", "final mutation"])],
    )

    assert matched[0]["bug_patch"]["buggy_code"] == "final mutation"


def test_stage_item_writes_test_and_bug_patch(tmp_path: Path) -> None:
    matched, _ = attach_bug_patches([_test_item()], [_bug_item()])

    _stage_item(matched[0], tmp_path)

    assert (tmp_path / "files/module/src/test/java/example/ReaderTests.java").is_file()
    patch_dir = tmp_path / "bug_patch"
    assert (patch_dir / "src_file.txt").read_text(encoding="utf-8").strip() == (
        "module/src/main/java/example/Reader.java"
    )
    assert (patch_dir / "original_code.txt").read_text(encoding="utf-8") == (
        "int read(int index) { return index; }"
    )
    assert (patch_dir / "buggy_code.txt").read_text(encoding="utf-8") == (
        "int read(int index) { return -index; }"
    )
