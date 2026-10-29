#!/bin/bash
set -uxo pipefail

cd /testbed
python -m pytest --no-header -rA --tb=no -p no:cacheprovider tests/
rc=$?
echo "OMNIGRIL_EXIT_CODE=$rc"
