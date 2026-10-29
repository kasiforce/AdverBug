"""临时调试脚本：对 kubernetes-client/java 单独计时，定位 screen_repo 卡点。"""
import sys, time, os

sys.path.insert(0, "/mnt/SoftwareTestingBenchmark/gen_test")
sys.path.insert(0, "/mnt/SoftwareTestingBenchmark")
os.chdir("/mnt/SoftwareTestingBenchmark/screen_work/java")

import screen_java_repo as S
from java_extractor import JavaProjectTestScopeExtractor

t0 = time.time()
files = S.list_tracked_files(".")
print(f"ls-files: {time.time()-t0:.1f}s", flush=True)

src_files = [f for f in files if "/src/main/java/" in f"/{f}" and f.endswith(".java")]
print(f"src files: {len(src_files)}", flush=True)

t0 = time.time()
ex = JavaProjectTestScopeExtractor(project_root=".", file_list=src_files,
                                   min_loc_threshold=5)
print(f"init: {time.time()-t0:.1f}s", flush=True)

t0 = time.time()
ex._parse_project()
print(f"parse_project: {time.time()-t0:.1f}s  classes={len(ex.classes)}", flush=True)

t0 = time.time()
n = 0
for cls_name, cls in ex.classes.items():
    for m in ex._compute_test_scope_for_class(cls_name):
        should_filter, _ = ex._should_filter_method(m)
        if should_filter:
            continue
        n += 1
print(f"compute_test_scope: {time.time()-t0:.1f}s  methods={n}", flush=True)
