#!/usr/bin/env bash
set -uo pipefail

trap 'chmod -R a+rwX /results 2>/dev/null || true' EXIT

cd /testbed
JACOCO_VERSION="${JACOCO_VERSION:-0.8.14}"

if [[ ! -f /eval-input/test_file.txt || ! -d /eval-input/files ]]; then
    echo "Missing staged evaluation input" >&2
    exit 90
fi

# Remove original Java test sources, while never deleting src/main production
# code.  The generated test and any allowed test configuration are copied in
# only after this cleanup.
while IFS= read -r -d '' source_file; do
    relative="${source_file#./}"
    lower="$(printf '%s' "/${relative}/" | tr '[:upper:]' '[:lower:]')"
    case "$lower" in
        */src/main/*) ;;
        */test/*|*/tests/*|*/__test__/*|*/__tests__/*|*/spec/*|*/specs/*|*/androidtest/*|*/testfixtures/*)
            rm -f -- "$source_file"
            ;;
    esac
done < <(find . -type f -name '*.java' -print0)

cp -a /eval-input/files/. /testbed/

TEST_FILE="$(tr -d '\r\n' < /eval-input/test_file.txt)"
TEST_CLASS="$(basename "$TEST_FILE" .java)"
TEST_DIR="$(dirname "$TEST_FILE")"
MODULE_DIR="$TEST_DIR"
while [[ "$MODULE_DIR" != "." && "$MODULE_DIR" != "/" && ! -f "$MODULE_DIR/pom.xml" ]]; do
    MODULE_DIR="$(dirname "$MODULE_DIR")"
done
if [[ ! -f "$MODULE_DIR/pom.xml" ]]; then
    if [[ -f pom.xml ]]; then
        MODULE_DIR="."
    else
        echo "Cannot find pom.xml for $TEST_FILE" >&2
        exit 91
    fi
fi
printf '%s\n' "$MODULE_DIR" > /results/module_dir.txt

if [[ -x /testbed/mvnw ]]; then
    MVN=(/testbed/mvnw)
elif command -v mvn >/dev/null 2>&1; then
    MVN=(mvn)
else
    echo "Neither mvn nor /testbed/mvnw is available" >&2
    exit 92
fi

COMMON=(-B -ntp -DskipTests=false -Dmaven.test.skip=false -DfailIfNoTests=false -Drat.skip=true)
cd "/testbed/$MODULE_DIR"

"${MVN[@]}" "${COMMON[@]}" clean test-compile > /results/compile.log 2>&1
COMPILE_EXIT=$?
printf '%s\n' "$COMPILE_EXIT" > /results/compile_exit_code.txt
if [[ $COMPILE_EXIT -ne 0 ]]; then
    exit 0
fi

# Undertow and a few other projects consume jacoco.agent.argLine instead of
# the default argLine.  Detect that convention from the effective project
# hierarchy and ask prepare-agent to populate the matching property.
PROPERTY_NAME="argLine"
scan_dir="/testbed/$MODULE_DIR"
while [[ "$scan_dir" == /testbed* ]]; do
    if [[ -f "$scan_dir/pom.xml" ]]; then
        configured_property="$(
            grep -E '<argLine>.*\$\{[^}]+\}' "$scan_dir/pom.xml" 2>/dev/null \
                | grep -o '\${[^}]*}' \
                | head -1 \
                | tr -d '${}' \
                || true
        )"
        if [[ -n "$configured_property" ]]; then
            PROPERTY_NAME="$configured_property"
            break
        fi
        if grep -q 'jacoco\.agent\.argLine' "$scan_dir/pom.xml"; then
            PROPERTY_NAME="jacoco.agent.argLine"
            break
        fi
    fi
    [[ "$scan_dir" == "/testbed" ]] && break
    scan_dir="$(dirname "$scan_dir")"
done

AGENT_JAR="/root/.m2/repository/org/jacoco/org.jacoco.agent/${JACOCO_VERSION}/org.jacoco.agent-${JACOCO_VERSION}-runtime.jar"
AGENT_ARGUMENT="-javaagent:${AGENT_JAR}=destfile=/results/jacoco.exec"

"${MVN[@]}" "${COMMON[@]}" \
    "org.jacoco:jacoco-maven-plugin:${JACOCO_VERSION}:prepare-agent" \
    test \
    "-Djacoco.destFile=/results/jacoco.exec" \
    "-Djacoco.propertyName=${PROPERTY_NAME}" \
    "-D${PROPERTY_NAME}=${AGENT_ARGUMENT}" \
    "-Dtest=${TEST_CLASS}" \
    -Dsurefire.failIfNoSpecifiedTests=false \
    > /results/test.log 2>&1
TEST_EXIT=$?
printf '%s\n' "$TEST_EXIT" > /results/test_exit_code.txt

mkdir -p /results/reports /results/jacoco-report
if [[ -d target/surefire-reports ]]; then
    find target/surefire-reports -maxdepth 1 -type f -name 'TEST-*.xml' -exec cp {} /results/reports/ \;
fi

if [[ -s /results/jacoco.exec ]]; then
    "${MVN[@]}" -B -ntp \
        "org.jacoco:jacoco-maven-plugin:${JACOCO_VERSION}:report" \
        "-Djacoco.dataFile=/results/jacoco.exec" \
        "-Djacoco.outputDirectory=/results/jacoco-report" \
        > /results/coverage.log 2>&1
    COVERAGE_EXIT=$?
    printf '%s\n' "$COVERAGE_EXIT" > /results/coverage_exit_code.txt
    if [[ -f /results/jacoco-report/jacoco.xml ]]; then
        cp /results/jacoco-report/jacoco.xml /results/jacoco.xml
    else
        fallback="$(find target -type f -path '*/site/jacoco/jacoco.xml' -print -quit 2>/dev/null || true)"
        [[ -n "$fallback" ]] && cp "$fallback" /results/jacoco.xml
    fi
fi

exit 0
