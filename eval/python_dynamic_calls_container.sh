#!/usr/bin/env bash
set -uo pipefail

# Reuse the regular evaluator first, then emit an unfiltered report for
# callees in other production files.  Running coverage first keeps its test
# execution independent from the later profile pass.
bash /eval/python_eval_container.sh
status=$?
if [[ -s /results/.coverage ]]; then
    coverage json --rcfile=/eval/python_coveragerc \
        --data-file=/results/.coverage -o /results/coverage_all.json \
        > /results/coverage_all.log 2>&1 || true
fi

cd /testbed
unset ADVER_TRACE_DISABLED
if [[ -f /eval-input/test_file.txt && -d /eval-input/files ]]; then
    cp -a /eval-input/files/. /testbed/
    TRACE_TEST_FILE="$(tr -d '\r\n' < /eval-input/test_file.txt)"
    if ! python -c 'import pytest_cov' >/dev/null 2>&1; then
        if compgen -G '/eval-wheels/pytest_cov-*.whl' >/dev/null; then
            python -m pip install --disable-pip-version-check --no-deps \
                /eval-wheels/pytest_cov-*.whl \
                > /results/pytest_cov_install.log 2>&1 || exit 93
        else
            python -m pip install --disable-pip-version-check pytest-cov \
                > /results/pytest_cov_install.log 2>&1 || exit 93
        fi
    fi
    # pytest-cov coordinates coverage across pytest-xdist workers, while the
    # trace plugin records direct caller-to-callee edges in the same run.
    python -m pytest "$TRACE_TEST_FILE" \
        --cov=. --cov-branch --cov-config=/eval/python_coveragerc \
        --cov-report=json:/results/coverage_all.json \
        -q --disable-warnings --tb=no \
        > /results/dynamic_trace_test.log 2>&1 || true
fi
exit "$status"
