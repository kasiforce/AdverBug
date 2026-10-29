#!/bin/bash
set -uxo pipefail

# Activate the `testbed` environment within the Docker container
source /opt/miniconda3/bin/activate
conda activate testbed

# Move to the testbed working directory containing the repository
cd /testbed

# Run the Maven-based test suite
mvn clean verify

# Capture the exit code and echo it for evaluation
rc=$?
echo "OMNIGRIL_EXIT_CODE=$rc"