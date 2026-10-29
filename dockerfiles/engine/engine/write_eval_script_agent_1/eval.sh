#!/bin/bash
set -uxo pipefail

# Navigate to the work directory
cd /testbed

# Install dependencies (this step is already in the Dockerfile)
npm install

# Execute the tests in the 'test' directory using the appropriate command
npm test
rc=$?  # Required, save exit code

# Log the exit code for evaluation
echo "OMNIGRIL_EXIT_CODE=$rc"  # Required, echo test status