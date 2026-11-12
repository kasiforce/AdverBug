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
test_files=("$test_file")
if [[ -f /eval-input/test_files.txt ]]; then
  mapfile -t test_files < <(tr -d '\r' < /eval-input/test_files.txt | sed '/^$/d')
fi
if [[ ${#test_files[@]} -eq 0 ]]; then
  echo "No staged test files" >&2
  exit 2
fi
for staged_test in "${test_files[@]}"; do
  if [[ -z "$staged_test" || "$staged_test" == /* || "$staged_test" == *".."* ]]; then
    echo "Unsafe staged test file path: $staged_test" >&2
    exit 2
  fi
done
src_file="$(tr -d '\r\n' < /eval-input/src_file.txt)"
if [[ -z "$src_file" || "$src_file" == /* || "$src_file" == *".."* ]]; then
  echo "Unsafe or empty source file path: $src_file" >&2
  exit 2
fi

cp -a /eval-input/files/. /testbed/

# Some projects deliberately exclude generated runtime entry points from Git.
# Generate them after staging tests so they reflect the checkout being tested.
case "${PROJECT_PRE_TEST_SETUP:-}" in
  "")
    ;;
  cyberchef)
    npx grunt configTests > /results/pre_test_setup.log 2>&1
    preparation_exit=$?
    printf '%s\n' "$preparation_exit" > /results/pre_test_setup_exit_code.txt
    if [[ "$preparation_exit" -ne 0 ]]; then
      echo "Project pre-test setup failed: npx grunt configTests" >&2
      printf '1\n' > /results/syntax_exit_code.txt
      printf '1\n' > /results/test_exit_code.txt
      printf '1\n' > /results/coverage_exit_code.txt
      exit 0
    fi
    ;;
  *)
    echo "Unknown PROJECT_PRE_TEST_SETUP: ${PROJECT_PRE_TEST_SETUP}" >&2
    exit 2
    ;;
esac

set +e
syntax_exit=0
for staged_test in "${test_files[@]}"; do
  node --check "$staged_test" >> /results/syntax.log 2>&1
  check_exit=$?
  if [[ "$check_exit" -ne 0 ]]; then
    syntax_exit=$check_exit
    break
  fi
done
set -e
printf '%s\n' "$syntax_exit" > /results/syntax_exit_code.txt

if [[ "${INSTALL_EVAL_DEPS:-0}" == "1" ]]; then
  eval_dependencies=()
  if ! command -v jest >/dev/null 2>&1 && [[ ! -x node_modules/.bin/jest ]]; then
    eval_dependencies+=(jest)
  fi

  # Jest 28+ no longer bundles the jsdom environment. Install it only when a
  # generated config or test explicitly requests jsdom and the project image
  # does not already provide it.
  if grep -RqsE \
      "testEnvironment[[:space:]]*:[[:space:]]*['\"]jsdom['\"]|@jest-environment[[:space:]]+jsdom" \
      /eval-input/files \
      && ! node -e "require.resolve('jest-environment-jsdom')" >/dev/null 2>&1; then
    jest_version=""
    if [[ -f node_modules/jest/package.json ]]; then
      jest_version="$(node -p "require('./node_modules/jest/package.json').version" 2>/dev/null || true)"
    elif [[ -f .adverbug_jest_runtime/node_modules/jest/package.json ]]; then
      jest_version="$(node -p "require('./.adverbug_jest_runtime/node_modules/jest/package.json').version" 2>/dev/null || true)"
    elif command -v jest >/dev/null 2>&1; then
      jest_version="$(jest --version 2>/dev/null || true)"
    fi
    if [[ "$jest_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([+-].*)?$ ]]; then
      eval_dependencies+=("jest-environment-jsdom@${jest_version}")
    else
      eval_dependencies+=(jest-environment-jsdom)
    fi
  fi

  if [[ ${#eval_dependencies[@]} -gt 0 ]]; then
    npm install --no-save --no-audit --no-fund "${eval_dependencies[@]}" \
      > /results/dependencies.log 2>&1 || true
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
ADVER_TRACE_DISABLED=1 "${jest_command[@]}" \
  --runTestsByPath "${test_files[@]}" \
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

coverage_collect_args=(--collectCoverageFrom="$src_file")
if [[ -f /eval-input/coverage_files.txt ]]; then
  coverage_collect_args=()
  while IFS= read -r coverage_file; do
    [[ -n "$coverage_file" ]] && coverage_collect_args+=(--collectCoverageFrom="$coverage_file")
  done < /eval-input/coverage_files.txt
elif [[ "${ADVER_TRACE_COLLECT_LOADED:-0}" == "1" ]]; then
  # Dynamic-call evaluation needs Istanbul data for callees in other files.
  # With no explicit pattern, Jest reports every production module loaded by
  # this isolated generated test.
  coverage_collect_args=()
fi

"${jest_command[@]}" \
  --runTestsByPath "${test_files[@]}" \
  --runInBand \
  --forceExit \
  --json \
  --outputFile=/results/coverage-report.json \
  --coverage \
  --coverageProvider="${JEST_COVERAGE_PROVIDER:-babel}" \
  "${coverage_collect_args[@]}" \
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
