#!/bin/bash
set -uxo pipefail

# Change to the project directory
cd /testbed

# Run all tests in the project
python -m pytest --no-header -rA --tb=short -p no:cacheprovider tests/
rc=$?  # Capture exit code of the test run

# Echo the exit code for result tracking
echo "OMNIGRIL_EXIT_CODE=$rc"
