#!/bin/bash
set -uxo pipefail

# Navigate to the working directory inside the container
cd /testbed

# Run all tests using Maven; ensure structured output
mvn test

# Capture the exit code from the test execution
rc=$?

# Report the exit code for judging
echo "OMNIGRIL_EXIT_CODE=$rc"