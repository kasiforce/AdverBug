#!/bin/bash
set -uxo pipefail

# Navigate to the project directory
cd /testbed

# Run the Python and optional C-extension unit tests.  `make check` also runs
# style hooks and can modify the checkout, which is not part of benchmark eval.
make unitc

# Capture the exit code of the test command execution
rc=$?

# Output the exit code for analysis
echo "OMNIGRIL_EXIT_CODE=$rc"
