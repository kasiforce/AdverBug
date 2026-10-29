#!/bin/bash
set -uxo pipefail

# Navigate to the project root
cd /testbed

# Ensure the Maven environment is initialized with the correct cache setup (already done in the Docker setup)
source /root/.bashrc

# Run the tests in the specified test directory with the proper Maven profiles and options
mvn clean install -e -B \
    -Dmaven.repo.local=$MAVEN_CACHE_FOLDER \
    -P JACOCO,CI \
    -f tests/hapi-fhir-base-test-mindeps-server/pom.xml

# Capture the exit code of the test execution
rc=$?

# Print exit code for verification
echo "OMNIGRIL_EXIT_CODE=$rc"

# Reset any modified files (if any)
git reset --hard