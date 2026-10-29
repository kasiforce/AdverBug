#!/bin/bash
set -uxo pipefail

cd /testbed/java
mvn -B -ntp test
rc=$?

# Output the final exit code
echo "OMNIGRIL_EXIT_CODE=$rc"
