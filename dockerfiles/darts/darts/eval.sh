#!/bin/bash
set -uxo pipefail

# Navigate to the project directory
cd /testbed

# Reset any potentially modified files before running tests
git reset --hard HEAD

# Run all tests in the test directory, formatted for concise output
pytest --no-header -rA --tb=no -p no:cacheprovider

# Capture the exit code of pytest execution
rc=$?

# Output a standard exit code marker for external analysis
echo "OMNIGRIL_EXIT_CODE=$rc"
