#!/usr/bin/env bash
set -euo pipefail

trap 'chmod -R a+rwX /results/coverage 2>/dev/null || true' EXIT

cd /testbed
COVERAGE_KIND="${COVERAGE_KIND:?COVERAGE_KIND is required}"
EXEC_MANIFEST="/results/${COVERAGE_KIND}_exec_manifest.txt"
FILE_GROUPS="/results/${COVERAGE_KIND}_file_groups.tsv"
OUTPUT_DIR="/results/coverage/${COVERAGE_KIND}"
mkdir -p "$OUTPUT_DIR" "$OUTPUT_DIR/files"

if ! python -c 'import coverage' >/dev/null 2>&1; then
    if [[ "${INSTALL_EVAL_DEPS:-1}" == "1" ]]; then
        python -m pip install coverage > "$OUTPUT_DIR/install.log" 2>&1
    else
        echo "coverage.py is unavailable" >&2
        exit 92
    fi
fi

data_files=()
while IFS= read -r relative; do
    [[ -z "$relative" ]] && continue
    [[ -s "/results/$relative" ]] && data_files+=("/results/$relative")
done < "$EXEC_MANIFEST"
[[ ${#data_files[@]} -gt 0 ]]

coverage combine --keep \
    --rcfile=/eval/python_coveragerc \
    --data-file="$OUTPUT_DIR/merged.coverage" \
    "${data_files[@]}"

# The evaluator consumes target-file reports below.  Avoid rendering a global
# JSON report here: with ``source = .`` coverage.py scans every Python source in
# large repositories, while that report is not used by any output metric.

cut -f1 "$FILE_GROUPS" | sort -u | while IFS= read -r file_slug; do
    [[ -z "$file_slug" ]] && continue
    src_file="$(awk -F '\t' -v slug="$file_slug" '$1 == slug { print $2; exit }' "$FILE_GROUPS")"
    group_data=()
    while IFS= read -r relative; do
        [[ -s "/results/$relative" ]] && group_data+=("/results/$relative")
    done < <(awk -F '\t' -v slug="$file_slug" '$1 == slug { print $3 }' "$FILE_GROUPS")
    [[ ${#group_data[@]} -gt 0 ]] || continue

    file_data="$OUTPUT_DIR/files/$file_slug.coverage"
    coverage combine --keep \
        --rcfile=/eval/python_coveragerc \
        --data-file="$file_data" \
        "${group_data[@]}"
    coverage json \
        --rcfile=/eval/python_coveragerc \
        --data-file="$file_data" \
        --include="$src_file" \
        -o "$OUTPUT_DIR/files/$file_slug.json"
done
