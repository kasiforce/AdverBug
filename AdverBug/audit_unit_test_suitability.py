#!/usr/bin/env python3
"""Conservatively audit benchmark focal functions for unit-test suitability.

The audit does not modify the benchmark.  It emits one row per focal function
with one of three decisions:

* exclude: strongly coupled to an external runtime or is a CLI/demo entrypoint;
* review: unit-testable, but likely to need a large fixture or extensive mocks;
* suitable: no strong testability concern found by the reviewed rules.

Rules intentionally use project/path/function identity rather than broad token
matching.  This keeps parsers that happen to process URLs, files, or sockets
from being incorrectly classified as external-I/O functions.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


def classify(language: str, project: str, item: dict) -> tuple[str, str, str]:
    """Return decision, category, and human-readable reason."""
    source = item.get("src_file", "")
    name = item.get("name", "")
    class_name = item.get("class_name") or ""

    # Java command-line/demo entrypoints embedded in production classes.
    if language == "java" and project == "TwelveMonkeys" and name == "main":
        return "exclude", "cli_or_demo_entrypoint", (
            "Production-class main method; behavior is dominated by argv, stdout/stderr, "
            "filesystem/ImageIO, classpath discovery, or System.exit."
        )

    if language == "java" and project == "leaf":
        if name == "createApplicationContext":
            return "exclude", "framework_bootstrap", (
                "Builds and refreshes a Spring ApplicationContext; this is framework/integration setup."
            )
        if name == "printConfiguration":
            return "review", "log_only_side_effect", (
                "Primary observable behavior is a large logging side effect requiring log capture."
            )

    if language == "java" and project == "undertow":
        external_runtime = {
            ("Undertow", "start"): "Starts XNIO workers, listeners, sockets, and SSL infrastructure.",
            ("ClientReadListener", "handleEvent"): "Asynchronous HTTP client channel callback with live connection state.",
            ("Http2ReceiveListener", "handleEvent"): "HTTP/2 receive callback requiring a configured channel and frames.",
            ("SslReadReadyHandler", "readReady"): "TLS/XNIO readiness callback tied to an SSL engine and channel.",
            ("UndertowAcceptingSslChannel", "accept"): "Accepts and wraps a real XNIO/SSL connection.",
            ("DefaultAccessLogReceiver", "run"): "Asynchronous access-log file writer/rotation task.",
            ("ContentEncodedResourceManager", "getResource"): "Reads and writes encoded resources through filesystem-backed managers.",
            ("SseWriteListener", "handleEvent"): "Non-blocking SSE channel callback with queued writes and listeners.",
            ("AlpnConnectionListener", "handleEvent"): "ALPN connection callback tied to an active network channel.",
            ("HttpReadListener", "handleEventWithNoRunningRequest"): "Top-level server read loop with channel dispatch and timeout state.",
            ("Transfer", "initiateTransfer"): "Initiates asynchronous source/sink channel transfer.",
            ("TransferListener", "handleEvent"): "Asynchronous channel-transfer listener state machine.",
        }
        reason = external_runtime.get((class_name, name))
        if reason:
            return "exclude", "network_or_async_runtime", reason

        if source.startswith("core/src/main/java/io/undertow/server/handlers/resource/"):
            return "review", "filesystem_fixture", (
                "Resource-manager behavior needs a filesystem tree, cache state, and exchange/sender fixtures."
            )
        if any(token in source for token in (
            "/client/", "/conduits/", "/protocols/ssl/", "/server/protocol/"
        )) or name in {"handleRequest", "send", "receiveFullString", "receivePartialString", "receiveFullBytes"}:
            return "review", "complex_framework_fixture", (
                "Requires multiple Undertow/XNIO channel or exchange objects and asynchronous state."
            )

    if language == "python" and project == "plotly" and name == "to_image":
        return "exclude", "external_renderer", (
            "Static image export depends on the optional Kaleido/browser rendering runtime."
        )

    if language == "python" and project == "sktime":
        if name == "write_files":
            return "exclude", "filesystem_side_effect", (
                "Writes benchmark prediction/probability files; observable behavior is filesystem output."
            )
        if (class_name, name) in {
            ("KronosPredictor", "predict_batch"),
            ("TimesFm", "forecast"),
            ("TimesFm", "forecast_with_covariates"),
            ("_SktimeModelWrapper", "predict"),
        }:
            return "exclude", "external_model_runtime", (
                "High-level inference wrapper requiring a loaded model and substantial third-party runtime state."
            )
        if source.startswith("sktime/libs/") and name in {
            "forward", "prepare_inputs_for_generation"
        }:
            return "review", "large_ml_fixture", (
                "Unit-testable with tensors, but requires heavyweight ML dependencies and model construction."
            )
        if name == "plot_critical_difference_diagram":
            return "review", "plotting_side_effect", (
                "Primarily constructs a plotting object and requires a plotting backend/fixture."
            )

    if language == "python" and project == "textual":
        if name == "import_app":
            return "exclude", "dynamic_import_environment", (
                "Loads a user application from a path/module and mutates import/environment state."
            )
        if (class_name, name) in {
            ("App", "push_screen"),
            ("App", "on_event"),
            ("WebDriver", "on_meta"),
        }:
            return "exclude", "terminal_event_runtime", (
                "Requires an active Textual application/driver event loop and message-pump state."
            )
        if source.startswith("src/textual/widgets/") or source.startswith("src/textual/layouts/"):
            return "review", "ui_widget_fixture", (
                "Needs a constructed widget/layout tree, styles, dimensions, or active app context."
            )

    if language == "js" and project == "CyberChef":
        if source.startswith("src/web/"):
            return "exclude", "browser_worker_runtime", (
                "Web-layer method depends on DOM elements, browser events, tabs, or Web Workers."
            )
        if name == "run" and any(token in source for token in (
            "AddTextToImage", "GenerateImage", "ImageHueSaturationLightness"
        )):
            return "exclude", "browser_canvas_runtime", (
                "Image operation requires Canvas/Image browser APIs not supplied by plain Node/Jest."
            )

    if language == "js" and project == "engine":
        if source == "src/framework/app-base.js" and name == "init":
            return "exclude", "engine_bootstrap", (
                "Initializes the application, graphics device, loaders, systems, and runtime services."
            )
        if source.startswith("src/framework/xr/"):
            return "exclude", "browser_xr_runtime", "Requires a live WebXR session/device and browser XR objects."
        if "/webgl/" in source or "/webgpu/" in source:
            return "exclude", "gpu_runtime", (
                "Executes against WebGL/WebGPU device resources; plain Jest has no real GPU context."
            )
        if source == "src/extras/exporters/core-exporter.js":
            return "exclude", "browser_canvas_runtime", (
                "Creates/draws browser canvas/image objects from a graphics texture."
            )
        if source.startswith("src/extras/effects/") or source.startswith("src/extras/mini-stats/"):
            return "exclude", "gpu_runtime", "Frame/render UI code requires an initialized graphics runtime."
        if source == "src/framework/lightmapper/lightmapper.js" and name == "bakeInternal":
            return "exclude", "gpu_runtime", "Runs the lightmapping render pipeline over scene/GPU resources."
        if source == "src/framework/components/particle-system/component.js" and name == "onEnable":
            return "exclude", "engine_lifecycle", "Component lifecycle hook requires an initialized scene/application."
        if source == "src/framework/components/rigid-body/system.js" and name == "onContactPair":
            return "exclude", "native_physics_runtime", "Callback depends on Ammo/native physics contact objects."
        if source == "src/framework/handlers/cubemap.js" and name == "loadAssets":
            return "exclude", "asset_loading_runtime", "Coordinates asynchronous asset-registry loading."
        if source == "src/scene/graphics/reproject-texture.js":
            return "exclude", "gpu_runtime", "Performs texture reprojection through render targets and shaders."
        if source == "src/scene/lighting/world-clusters-debug.js" and name == "render":
            return "exclude", "gpu_runtime", "Debug renderer requires scene, camera, mesh, and GPU state."
        if source == "src/scene/particle-system/gpu-updater.js":
            return "exclude", "gpu_runtime", "Particle update is implemented through GPU shader execution."
        if source.startswith("src/scene/renderer/"):
            return "exclude", "gpu_runtime", "Renderer method requires a complete scene and graphics device."
        if any(token in source for token in (
            "src/scene/particle-system/", "src/scene/gsplat-unified/", "src/scene/mesh"
        )):
            return "review", "engine_scene_fixture", (
                "Unit-testable only with a sizable scene/graphics-device fixture and extensive mocks."
            )

    if language == "js" and project == "eslint":
        if source == "lib/rules/comma-dangle.js" and name in {
            "forbidTrailingComma", "forceTrailingComma"
        }:
            return "exclude", "invalid_metric_boundary", (
                "Legacy Lizard result inherited the enclosing function range; the corrected "
                "function NLOC is below the benchmark LOC>=50 threshold."
            )
        if source == "lib/cli.js" and name == "execute":
            return "exclude", "cli_orchestration", (
                "Top-level CLI parses argv, logs, reads stdin/files/config, and returns process exit codes."
            )
        if name in {"lintFile", "lintFiles"}:
            return "exclude", "filesystem_worker_runtime", (
                "Discovers/reads files and may create worker threads and update on-disk caches."
            )
        if source == "tools/eslint-fuzzer.js" and name == "fuzz":
            return "exclude", "random_fuzz_harness", (
                "Long-running random fuzz harness rather than a deterministic production unit."
            )

    if language == "js" and project == "undici":
        if class_name == "SqliteCacheStore" and name == "set":
            return "exclude", "database_runtime", (
                "Mutates a SQLite cache through prepared statements and optional native compression."
            )
        if class_name == "Cache" and name == "addAll":
            return "exclude", "network_runtime", (
                "Starts actual Fetch operations for every request before mutating the cache."
            )
        if class_name == "Socks5Client" and name == "handleConnectResponse":
            return "review", "socket_state_fixture", (
                "Parsing is deterministic, but the method also mutates a live socket/listener state machine."
            )

    if language == "js" and project == "imba":
        if source == "packages/imba/polyfills/crypto/esm/lib/parse-asn1/index.js":
            return "exclude", "unloadable_vendored_module", (
                "Vendored crypto polyfill cannot be imported by the independent Jest runtime "
                "because its legacy ESM dependency specifiers are not Node-resolvable."
            )
        if source.startswith("packages/imba/src/compiler/"):
            return "review", "compiler_ast_fixture", (
                "Compiler method is deterministic, but needs a constructed Imba AST/scope fixture."
            )

    if language == "js" and project == "opentype.js":
        if source == "src/tables/fvar.mjs" and name == "parseFvarTable":
            return "exclude", "invalid_metric_boundary", (
                "Legacy Lizard result inherited the enclosing function range; the corrected "
                "function NLOC is below the benchmark LOC>=50 threshold."
            )

    # Broad but non-excluding reviewed groups, applied only after exact rules.
    if language == "java" and project == "ofdrw" and any(
        token in source for token in ("/render/", "ResManager.java", "ResourceManage.java")
    ):
        return "review", "document_render_fixture", (
            "Requires a constructed OFD document/resource/render context and output side effects."
        )
    if language == "java" and project == "TwelveMonkeys" and "ImageReader" in class_name:
        return "review", "binary_image_fixture", (
            "Needs correctly structured binary ImageIO input and reader state; still suitable with fixtures."
        )
    if language == "python" and project == "plotly" and (
        "renderer.py" in source or source.startswith("plotly/figure_factory/")
    ):
        return "review", "plotting_fixture", (
            "Needs Matplotlib/Plotly figure and renderer state but can be tested in memory."
        )

    return "suitable", "none", "No strong external-runtime or fixture concern identified."


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset-dir", type=Path,
        default=Path("dataset/benchmark_balanced_200_call_degree"),
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path("dataset/benchmark_balanced_200_call_degree/suitability"),
    )
    args = parser.parse_args()

    rows = []
    for language in ("java", "python", "js"):
        for path in sorted((args.dataset_dir / language).glob("*.json")):
            records = json.loads(path.read_text(encoding="utf-8"))
            for index, item in enumerate(records):
                decision, category, reason = classify(language, path.stem, item)
                rows.append({
                    "decision": decision,
                    "category": category,
                    "reason": reason,
                    "language": language,
                    "project": path.stem,
                    "json_index": index,
                    "src_file": item.get("src_file", ""),
                    "start_line": item.get("start_line", ""),
                    "end_line": item.get("end_line", ""),
                    "class_name": item.get("class_name", ""),
                    "function_name": item.get("name", ""),
                    "loc": item.get("loc", ""),
                    "complexity": item.get("complexity", ""),
                    "outgoing_degree": item.get("outgoing_degree", ""),
                })

    args.output_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0])
    with (args.output_dir / "function_suitability_audit.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    excluded = [row for row in rows if row["decision"] == "exclude"]
    with (args.output_dir / "recommended_exclusions.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(excluded)

    by_language = defaultdict(Counter)
    by_project = defaultdict(Counter)
    by_category = Counter()
    for row in rows:
        by_language[row["language"]][row["decision"]] += 1
        by_project[f'{row["language"]}/{row["project"]}'][row["decision"]] += 1
        if row["decision"] == "exclude":
            by_category[row["category"]] += 1
    summary = {
        "total": len(rows),
        "decision_counts": dict(Counter(row["decision"] for row in rows)),
        "by_language": {key: dict(value) for key, value in by_language.items()},
        "by_project": {key: dict(value) for key, value in by_project.items()},
        "exclusion_categories": dict(by_category),
        "policy": (
            "Conservative reviewed rules: exclude only clear external-runtime, CLI/demo, "
            "browser/GPU, database, model-runtime, event-loop coupling, or confirmed invalid "
            "metric boundaries. Review rows remain eligible unless manual inspection decides "
            "otherwise."
        ),
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
