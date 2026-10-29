#!/bin/bash
set -uxo pipefail

# Run outside the source checkout so Python imports the built wheel instead of
# scikit-learn's source-tree editable loader.
cd /tmp

# Run the test suite using pytest and capture the output concisely
pytest --no-header -rA --tb=no -p no:cacheprovider /testbed/sklearn
rc=$?  # Capture the exit code of the test command

# Output the exit code for evaluation
echo "OMNIGRIL_EXIT_CODE=$rc"
