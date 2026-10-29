#!/usr/bin/env bash
set -uo pipefail

trap 'chmod -R a+rwX /results 2>/dev/null || true' EXIT

mkdir -p /results/coverage
cd /testbed

test_file="$(tr -d '\r\n' < /eval-input/test_file.txt)"
if [[ -z "$test_file" || "$test_file" == /* || "$test_file" == *".."* ]]; then
  echo "Unsafe or empty test file path: $test_file" >&2
  exit 2
fi
src_file="$(tr -d '\r\n' < /eval-input/src_file.txt)"
if [[ -z "$src_file" || "$src_file" == /* || "$src_file" == *".."* ]]; then
  echo "Unsafe or empty source file path: $src_file" >&2
  exit 2
fi

cp -a /eval-input/files/. /testbed/

set +e
node --check "$test_file" > /results/syntax.log 2>&1
syntax_exit=$?
set -e
printf '%s\n' "$syntax_exit" > /results/syntax_exit_code.txt

if [[ "${INSTALL_EVAL_DEPS:-0}" == "1" ]]; then
  if ! command -v jest >/dev/null 2>&1 && [[ ! -x node_modules/.bin/jest ]]; then
    npm install --no-save --no-audit --no-fund jest > /results/dependencies.log 2>&1 || true
  fi
fi

jest_command=()
if [[ -x node_modules/.bin/jest ]]; then
  jest_command=(node_modules/.bin/jest)
elif [[ -x .adverbug_jest_runtime/node_modules/.bin/jest ]]; then
  jest_command=(.adverbug_jest_runtime/node_modules/.bin/jest)
elif command -v jest >/dev/null 2>&1; then
  jest_command=(jest)
elif npx --no-install jest --version >/dev/null 2>&1; then
  jest_command=(npx --no-install jest)
else
  echo "Jest executable not found" > /results/test.log
  printf '127\n' > /results/test_exit_code.txt
  exit 0
fi

export NODE_OPTIONS="${NODE_OPTIONS:-} --experimental-vm-modules"
set +e
"${jest_command[@]}" \
  --runTestsByPath "$test_file" \
  --runInBand \
  --forceExit \
  --json \
  --outputFile=/results/report.json \
  --modulePathIgnorePatterns=/testbed/tests/fixtures/ \
  --modulePathIgnorePatterns=/testbed/test/fixtures/ \
  --testTimeout="${JEST_TEST_TIMEOUT_MS:-60000}" \
  > /results/test.log 2>&1
test_exit=$?
printf '%s\n' "$test_exit" > /results/test_exit_code.txt

"${jest_command[@]}" \
  --runTestsByPath "$test_file" \
  --runInBand \
  --forceExit \
  --json \
  --outputFile=/results/coverage-report.json \
  --coverage \
  --coverageProvider="${JEST_COVERAGE_PROVIDER:-babel}" \
  --collectCoverageFrom="$src_file" \
  --coverageDirectory=/results/coverage \
  --coverageReporters=json \
  --coverageReporters=json-summary \
  --modulePathIgnorePatterns=/testbed/tests/fixtures/ \
  --modulePathIgnorePatterns=/testbed/test/fixtures/ \
  --testTimeout="${JEST_TEST_TIMEOUT_MS:-60000}" \
  > /results/coverage.log 2>&1
coverage_exit=$?
set -e
printf '%s\n' "$coverage_exit" > /results/coverage_exit_code.txt

exit 0
