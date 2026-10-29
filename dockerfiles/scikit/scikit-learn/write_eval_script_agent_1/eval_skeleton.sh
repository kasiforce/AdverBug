#!/bin/bash
set -uxo pipefail

# Activate the Conda environment
source /opt/miniconda3/etc/profile.d/conda.sh
conda activate testbed

# Navigate to the testbed directory
cd /testbed

# Run the test suite using pytest and capture the output concisely
pytest --no-header -rA --tb=no -p no:cacheprovider sklearn
rc=$?  # Capture the exit code of the test command

# Output the exit code for evaluation
echo "OMNIGRIL_EXIT_CODE=$rc"