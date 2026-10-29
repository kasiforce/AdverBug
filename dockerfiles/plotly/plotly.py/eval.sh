#!/bin/bash
set -uxo pipefail

# Change to the working directory where the repository is cloned
cd /testbed || { echo "Failed to change directory to /testbed"; exit 1; }

# Execute the target test directory using pytest
python -m pytest --no-header -rA --tb=no -p no:cacheprovider test_init tests/
rc=$?  # Capture the exit code of the pytest command

# Echo the exit code for evaluation
echo "OMNIGRIL_EXIT_CODE=$rc"
