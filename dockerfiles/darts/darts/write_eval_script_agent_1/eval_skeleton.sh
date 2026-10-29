#!/bin/bash
set -uxo pipefail

# Activate the testbed environment
source /opt/miniconda3/etc/profile.d/conda.sh
conda activate testbed

# Navigate to the project directory
cd /testbed

# Ensure pre-commit hooks are configured (already done in Docker)
# Reset any potentially modified files before running tests
git reset --hard HEAD

# Run all tests in the test directory, formatted for concise output
uv run pytest --no-header -rA --tb=no -p no:cacheprovider

# Capture the exit code of pytest execution
rc=$?

# Output a standard exit code marker for external analysis
echo "OMNIGRIL_EXIT_CODE=$rc"