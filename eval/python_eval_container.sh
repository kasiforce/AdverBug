#!/usr/bin/env bash
set -uo pipefail

trap 'chmod -R a+rwX /results 2>/dev/null || true' EXIT

cd /testbed

if [[ ! -f /eval-input/test_file.txt || ! -f /eval-input/src_file.txt || ! -d /eval-input/files ]]; then
    echo "Missing staged evaluation input" >&2
    exit 90
fi

if ! python -c 'import coverage, pytest, pytest_jsonreport, pytest_timeout, pytest_asyncio, pytest_mock' >/dev/null 2>&1; then
    if [[ "${INSTALL_EVAL_DEPS:-1}" == "1" ]]; then
        python -m pip install pytest pytest-json-report pytest-timeout coverage pytest-asyncio pytest-mock \
            > /results/dependencies.log 2>&1 || exit 92
    else
        echo "Required pytest/coverage evaluation dependencies are unavailable" \
            > /results/dependencies.log
        exit 92
    fi
fi

cp -a /eval-input/files/. /testbed/
TEST_FILE="$(tr -d '\r\n' < /eval-input/test_file.txt)"
SRC_FILE="$(tr -d '\r\n' < /eval-input/src_file.txt)"

python -m pytest "$TEST_FILE" \
    --collect-only \
    --import-mode=importlib \
    -q --disable-warnings --tb=no \
    > /results/compile.log 2>&1
COMPILE_EXIT=$?
printf '%s\n' "$COMPILE_EXIT" > /results/compile_exit_code.txt
if [[ $COMPILE_EXIT -ne 0 && $COMPILE_EXIT -ne 5 ]]; then
    exit 0
fi

coverage run \
    --rcfile=/eval/python_coveragerc \
    --data-file=/results/.coverage \
    -m pytest "$TEST_FILE" \
    --import-mode=importlib \
    --timeout="${PYTEST_TIMEOUT:-60}" \
    -q --disable-warnings --tb=no \
    --json-report \
    --json-report-file=/results/report.json \
    > /results/test.log 2>&1
TEST_EXIT=$?
printf '%s\n' "$TEST_EXIT" > /results/test_exit_code.txt

if [[ -s /results/.coverage ]]; then
    coverage json \
        --rcfile=/eval/python_coveragerc \
        --data-file=/results/.coverage \
        --include="$SRC_FILE" \
        -o /results/coverage.json \
        > /results/coverage.log 2>&1
    printf '%s\n' "$?" > /results/coverage_exit_code.txt
fi

exit 0
