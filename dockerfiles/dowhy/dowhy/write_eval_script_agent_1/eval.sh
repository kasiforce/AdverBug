#!/bin/bash
set -uxo pipefail

# Activate Conda environment
source /opt/miniconda3/etc/profile.d/conda.sh
conda activate testbed

# Navigate to the project directory
cd /testbed

# Ensure dependencies and extras are installed
pip install -e .

# Execute tests in parallel with detailed test result output
pytest --no-header -rA --tb=no -p no:cacheprovider -n auto tests/
rc=$?  # Capture the exit code

# Cleanup: Reset any modified files or state
git reset --hard

# Output test exit status for evaluation
echo "OMNIGRIL_EXIT_CODE=$rc"