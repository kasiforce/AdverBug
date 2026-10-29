#!/usr/bin/env python3
"""Remove Java functions that are clearly outside isolated unit-test scope."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


# These are command-line entry points, server lifecycle methods, background
# worker loops, or benchmark setup hooks.  They are intentionally kept out of
# the unit-test benchmark; borderline I/O and callback methods remain eligible.
EXCLUDED = {
    (
        "parquet-benchmarks/src/main/java/org/apache/parquet/variant/VariantBuilderBenchmark.java",
        "VariantBuilderBenchmark",
        "setupTrial",
    ),
    ("parquet-cli/src/main/java/org/apache/parquet/cli/Main.java", "Main", "run"),
    (
        "parquet-cli/src/main/java/org/apache/parquet/cli/commands/ConvertCSVCommand.java",
        "ConvertCSVCommand",
        "run",
    ),
    (
        "parquet-cli/src/main/java/org/apache/parquet/cli/commands/ShowColumnIndexCommand.java",
        "ShowColumnIndexCommand",
        "run",
    ),
    (
        "parquet-cli/src/main/java/org/apache/parquet/cli/commands/ShowPagesCommand.java",
        "ShowPagesCommand",
        "run",
    ),
    (
        "parquet-hadoop/src/main/java/org/apache/parquet/hadoop/PrintFooter.java",
        "PrintFooter",
        "main",
    ),
    ("core/src/main/java/io/undertow/Undertow.java", "Undertow", "start"),
    (
        "core/src/main/java/io/undertow/server/handlers/accesslog/DefaultAccessLogReceiver.java",
        "DefaultAccessLogReceiver",
        "run",
    ),
}


def is_excluded(entry: dict) -> bool:
    return (
        str(entry.get("src_file", "")),
        str(entry.get("class_name", "")),
        str(entry.get("name", "")),
    ) in EXCLUDED or (
        str(entry.get("src_file", ""))
        in {
            "common/common-image/src/main/java/com/twelvemonkeys/image/IndexImage.java",
            "common/common-io/src/main/java/com/twelvemonkeys/net/MIMEUtil.java",
            "common/common-lang/src/main/java/com/twelvemonkeys/util/service/ServiceRegistry.java",
            "imageio/imageio-psd/src/main/java/com/twelvemonkeys/imageio/plugins/psd/PSDImageReader.java",
            "imageio/imageio-tiff/src/main/java/com/twelvemonkeys/imageio/plugins/tiff/TIFFImageWriter.java",
        }
        and str(entry.get("name", "")) == "main"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    total = removed = 0
    for source in sorted(args.input_dir.glob("*.json")):
        entries = json.loads(source.read_text(encoding="utf-8"))
        kept = []
        removed_entries = []
        for entry in entries:
            total += 1
            if is_excluded(entry):
                removed += 1
                removed_entries.append(entry)
            else:
                kept.append(entry)
        target = args.output_dir / source.name
        target.write_text(json.dumps(kept, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{source.name}: {len(entries)} -> {len(kept)}")
        for entry in removed_entries:
            print(f"  removed {entry.get('class_name')}.{entry.get('name')} ({entry.get('src_file')})")

    print(f"total: {total} -> {total - removed}; removed: {removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
