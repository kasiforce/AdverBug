#!/bin/bash
set -uxo pipefail

# Activate Conda environment
source /opt/miniconda3/etc/profile.d/conda.sh
conda activate testbed

# Change to the project directory
cd /testbed

# Run all tests in the project
pytest --no-header -rA --tb=short -p no:cacheprovider -n auto tests/
rc=$?  # Capture exit code of the test run

# Echo the exit code for result tracking
echo "OMNIGRIL_EXIT_CODE=$rc"