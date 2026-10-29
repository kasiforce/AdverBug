#!/bin/bash
set -uxo pipefail

# Navigate to the working directory
cd /testbed

# Activate the environment (set PATH for Maven, already set during Docker build)
source /root/.bashrc

# Install project dependencies (reinstall for safety to avoid environment issues)
mvn clean install -DskipTests

# Execute the tests excluding the specified modules
mvn test \
  -Dtest=!pdfbox/**,!fontbox/**,!io/**,!xmpbox/**,!tools/**,!examples/** 

# Capture the exit code of the test command
rc=$?

# Echo the exit code so it can be analyzed
echo "OMNIGRIL_EXIT_CODE=$rc"

# Ensure proper cleanup by resetting any potentially modified files
git reset --hard