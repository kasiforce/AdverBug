#!/bin/bash
set -uxo pipefail

# Navigate to the project directory
cd /testbed

# Ensure dependencies and extras are installed
pip install -e .

# Execute tests with detailed test result output.  Keep the command serial so
# it does not depend on pytest-xdist being installed by the project itself.
pytest --no-header -rA --tb=no -p no:cacheprovider tests/
rc=$?  # Capture the exit code

# Cleanup: Reset any modified files or state
git reset --hard

# Output test exit status for evaluation
echo "OMNIGRIL_EXIT_CODE=$rc"
