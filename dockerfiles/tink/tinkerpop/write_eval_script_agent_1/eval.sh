#!/bin/bash
set -uxo pipefail

# Move to the project root directory
cd /testbed

# Ensure the environment is correctly set up for testing
source /root/.bashrc

# Maven provides the necessary test execution flexibility. Combining Unit and Integration Test commands:
# Execute unit tests with the specified JVM arguments and ensure integration tests are skipped by default.
mvn test -DskipIntegrationTests=true -Dlogback.configuration=file:target/test-classes/logback-test.xml \
         -Dlog4j.configuration=file:target/test-classes/log4j-test.properties \
         -Dslf4j.provider=ch.qos.logback.classic.spi.LogbackServiceProvider \
         -Dbuild.dir=${project.build.directory} \
         -Dis.testing=true \
         -Djava.net.preferIPv4Stack=true ${suresafeArgs} ${jdk17JvmArgs}

# Capture the unit test exit code
rc1=$?
echo "Unit Test Exit Code: $rc1"

# If the unit tests passed, execute integration tests by overriding the default skip behavior
if [ $rc1 -eq 0 ]; then
    mvn verify -DskipIntegrationTests=false -Dlogback.configuration=file:target/test-classes/logback-test.xml \
               -Dlog4j.configuration=file:target/test-classes/log4j-test.properties \
               -Dslf4j.provider=ch.qos.logback.classic.spi.LogbackServiceProvider \
               -Dhost=localhost -Dport=8182 \
               -Dbuild.dir=${project.build.directory} \
               -Dis.testing=true \
               -Djava.net.preferIPv4Stack=true ${suresafeArgs} ${jdk17JvmArgs}

    # Capture the integration test exit code
    rc2=$?
    echo "Integration Test Exit Code: $rc2"
else
    rc2=0  # Skip integration tests if unit tests fail
    echo "Integration test skipped due to unit test failure."
fi

# Combine the exit codes
if [ $rc1 -eq 0 ] && [ $rc2 -eq 0 ]; then
    rc=0  # Both tests passed
else
    rc=1  # Either test failed
fi

# Reset any modified files to ensure a clean state
git reset --hard HEAD

# Required: Output the overall exit code
echo "OMNIGRIL_EXIT_CODE=$rc"