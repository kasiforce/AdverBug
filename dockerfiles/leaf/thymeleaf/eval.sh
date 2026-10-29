#!/bin/bash
set -uxo pipefail

# Ensure we are in the correct working directory
cd /testbed

# Run Maven tests in the target test directory including submodules
mvn -B -ntp -pl "$THYMELEAF_TEST_MODULES" -am test

# Capture the exit code from the Maven test execution
rc=$?

# Print the exit code for evaluation
echo "OMNIGRIL_EXIT_CODE=$rc"
