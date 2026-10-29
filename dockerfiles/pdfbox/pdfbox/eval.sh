#!/bin/bash
set -uxo pipefail

# Navigate to the working directory
cd /testbed

# Run the complete Maven test phase for all reactor modules. Fixture downloads
# are retained between attempts, so transient issue.apache.org timeouts recover.
attempt=1
until mvn -B -ntp test; do
    if [ "$attempt" -ge 10 ]; then
        break
    fi
    attempt=$((attempt + 1))
    echo "Retrying PDFBox tests (attempt $attempt/10)"
done

# Capture the exit code of the test command
rc=$?

# Echo the exit code so it can be analyzed
echo "OMNIGRIL_EXIT_CODE=$rc"
