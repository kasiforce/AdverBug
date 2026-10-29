#!/bin/bash
set -uxo pipefail

# Activate the environment
source /root/.nvm/nvm.sh
nvm use default

# Move to the testbed directory (root of the project)
cd /testbed

# Run tests using Vitest from the test directory
npx vitest run --reporter=default
rc=$? # Required, save the exit code

# Output the exit code for logging purposes
echo "OMNIGRIL_EXIT_CODE=$rc" # Required, echo test status

# Ensure no changes remain in the repository
git reset --hard