#!/bin/bash
set -uxo pipefail

# Navigate to the testbed directory where the project is located
cd /testbed

# Ensure Java 17 environment is activated correctly
source /root/.bashrc

# Run Maven test command to execute the test suite
mvn -Dfile.encoding=UTF-8 clean test

# Capture the exit code immediately after running the tests
rc=$?

# Output OMNIGRIL exit code for processing by test log analysis agent
echo "OMNIGRIL_EXIT_CODE=$rc"