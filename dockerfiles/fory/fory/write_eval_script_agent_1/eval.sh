#!/bin/bash
set -uxo pipefail

# Activate the Conda environment
source /opt/miniconda3/etc/profile.d/conda.sh
conda activate testbed

# Navigate to the testbed directory
cd /testbed

# Run Python tests
cd python
pytest -v -s . || true
rc_python=$?

# Run Java tests
cd ../java
mvn -T10 clean test || true
rc_java=$?

# Run C++ tests
cd ../cpp
bazel test $(bazel query //...) || true
rc_cpp=$?

# Run Go tests
cd ../go/fory
go test -v ./... || true
rc_go=$?

# Run Rust tests
cd ../../rust
cargo test || true
rc_rust=$?

# Run JavaScript tests
cd ../javascript
npm run test || true
rc_javascript=$?

# Combine all exit codes into a single result
rc=$((rc_python | rc_java | rc_cpp | rc_go | rc_rust | rc_javascript))

# Output the final exit code
echo "OMNIGRIL_EXIT_CODE=$rc"