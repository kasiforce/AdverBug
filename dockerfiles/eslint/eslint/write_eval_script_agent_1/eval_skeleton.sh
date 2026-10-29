#!/bin/bash
set -uxo pipefail

# Navigate to the project directory
cd /testbed

# Ensure any previously modified files are reset
git reset --hard

# Install all necessary dependencies
npm install

# Execute all tests in the project
npm run test
rc=$? # Capture the exit code of the test command

# Echo the exit code for evaluation
echo "OMNIGRIL_EXIT_CODE=$rc"