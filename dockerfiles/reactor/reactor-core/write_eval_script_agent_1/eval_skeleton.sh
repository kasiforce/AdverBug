#!/bin/bash
set -uxo pipefail

# Activate SDKMAN environment for JDK management
source /root/.sdkman/bin/sdkman-init.sh

# Set the working directory
cd /testbed

# Run the Gradle tests in the project
./gradlew test --no-daemon --stacktrace

# Save exit code from the test execution
rc=$?

# Output the exit code for OMNIGRIL to analyze
echo "OMNIGRIL_EXIT_CODE=$rc"

# Cleanup: Reset any modified files in the repo
git reset --hard