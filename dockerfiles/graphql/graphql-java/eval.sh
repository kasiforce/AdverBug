#!/bin/bash
set -uxo pipefail

# Navigate to the project directory
cd /testbed

# graphql-java is a Gradle-only project (there is no pom.xml).
./gradlew --no-daemon test

# Capture the exit code
rc=$?

# Output the exit code for validation
echo "OMNIGRIL_EXIT_CODE=$rc"
