#!/bin/bash
set -uxo pipefail

# Navigate to the cloned repository inside the container
cd /testbed

# Run Maven tests using the appropriate profile and settings
# - Ensures that tests output pass/fail/skip or errors (via Surefire reports)
# - Test results will be saved in `target/surefire-reports/TEST-*.xml` for structured analysis.
mvn test -B -ntp -T 1C -Dmaven.wagon.http.retryHandler.count=10 -Dtest='!OpenSsl*' -pl '!codec-native-quic,!codec-http3,!all,!testsuite-jpms,!testsuite-native,!testsuite-native-image,!testsuite-native-image-client,!testsuite-native-image-client-runtime-init,!testsuite-karaf,!testsuite-osgi,!testsuite-shading,!microbench,!example' -am

# Capture the exit code to check if the tests passed or failed
rc=$?

# Output the test execution status for analysis
echo "OMNIGRIL_EXIT_CODE=$rc"
