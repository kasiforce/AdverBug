#!/bin/bash
set -uxo pipefail

# Move to the testbed working directory containing the repository
cd /testbed

# Run the Maven-based test suite without interactive transfer progress.
mvn --batch-mode --no-transfer-progress clean verify

# Capture the exit code and echo it for evaluation
rc=$?
echo "OMNIGRIL_EXIT_CODE=$rc"
