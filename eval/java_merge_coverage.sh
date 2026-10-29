#!/usr/bin/env bash
set -euo pipefail

trap 'chmod -R a+rwX /results/coverage 2>/dev/null || true' EXIT

cd /testbed
JACOCO_VERSION="${JACOCO_VERSION:-0.8.14}"
COVERAGE_KIND="${COVERAGE_KIND:?COVERAGE_KIND is required}"
EXEC_MANIFEST="/results/${COVERAGE_KIND}_exec_manifest.txt"
FILE_GROUPS="/results/${COVERAGE_KIND}_file_groups.tsv"
MODULE_MANIFEST="/results/module_manifest.tsv"
OUTPUT_DIR="/results/coverage/${COVERAGE_KIND}"
mkdir -p "$OUTPUT_DIR" "$OUTPUT_DIR/files"

if [[ -x /testbed/mvnw ]]; then
    MVN=(/testbed/mvnw)
else
    MVN=(mvn)
fi

"${MVN[@]}" -B -ntp \
    org.apache.maven.plugins:maven-dependency-plugin:3.8.1:get \
    "-Dartifact=org.jacoco:org.jacoco.cli:${JACOCO_VERSION}:jar:nodeps" \
    > "$OUTPUT_DIR/get-jacoco-cli.log" 2>&1

CLI_JAR="/root/.m2/repository/org/jacoco/org.jacoco.cli/${JACOCO_VERSION}/org.jacoco.cli-${JACOCO_VERSION}-nodeps.jar"
[[ -f "$CLI_JAR" ]]

exec_files=()
while IFS= read -r relative; do
    [[ -z "$relative" ]] && continue
    [[ -s "/results/$relative" ]] && exec_files+=("/results/$relative")
done < "$EXEC_MANIFEST"
[[ ${#exec_files[@]} -gt 0 ]]

if [[ ${#exec_files[@]} -eq 1 ]]; then
    cp "${exec_files[0]}" "$OUTPUT_DIR/merged.exec"
else
    java -jar "$CLI_JAR" merge "${exec_files[@]}" --destfile "$OUTPUT_DIR/merged.exec"
fi

while IFS=$'\t' read -r slug module; do
    [[ -z "$slug" ]] && continue
    if [[ "$module" == "." ]]; then
        module_root="/testbed"
    else
        module_root="/testbed/$module"
    fi
    class_dir="$module_root/target/classes"
    source_dir="$module_root/src/main/java"
    if [[ ! -d "$class_dir" || ! -d "$source_dir" ]]; then
        printf 'Missing class/source directory for module %s\n' "$module" >&2
        continue
    fi
    java -jar "$CLI_JAR" report "$OUTPUT_DIR/merged.exec" \
        --classfiles "$class_dir" \
        --sourcefiles "$source_dir" \
        --xml "$OUTPUT_DIR/$slug.xml"
done < "$MODULE_MANIFEST"

# File coverage is target-specific: for each source file, merge only exec data
# produced by tests whose benchmark target belongs to that source file.  This
# prevents tests for unrelated files from inflating its coverage.
cut -f1 "$FILE_GROUPS" | sort -u | while IFS= read -r file_slug; do
    [[ -z "$file_slug" ]] && continue
    module="$(awk -F '\t' -v slug="$file_slug" '$1 == slug { print $2; exit }' "$FILE_GROUPS")"
    src_file="$(awk -F '\t' -v slug="$file_slug" '$1 == slug { print $3; exit }' "$FILE_GROUPS")"
    group_execs=()
    while IFS= read -r relative; do
        [[ -s "/results/$relative" ]] && group_execs+=("/results/$relative")
    done < <(awk -F '\t' -v slug="$file_slug" '$1 == slug { print $4 }' "$FILE_GROUPS")
    [[ ${#group_execs[@]} -gt 0 ]] || continue

    file_exec="$OUTPUT_DIR/files/$file_slug.exec"
    if [[ ${#group_execs[@]} -eq 1 ]]; then
        cp "${group_execs[0]}" "$file_exec"
    else
        java -jar "$CLI_JAR" merge "${group_execs[@]}" --destfile "$file_exec"
    fi

    if [[ "$module" == "." ]]; then
        module_root="/testbed"
    else
        module_root="/testbed/$module"
    fi
    class_dir="$module_root/target/classes"
    source_dir="$module_root/src/main/java"
    relative_source="${src_file#*src/main/java/}"
    relative_class="${relative_source%.java}"
    class_parent="$class_dir/$(dirname "$relative_class")"
    class_stem="$(basename "$relative_class")"
    class_args=()
    if [[ -d "$class_parent" ]]; then
        while IFS= read -r -d '' class_file; do
            class_args+=(--classfiles "$class_file")
        done < <(find "$class_parent" -maxdepth 1 -type f \
            \( -name "${class_stem}.class" -o -name "${class_stem}\$*.class" \) -print0)
    fi
    if [[ ${#class_args[@]} -eq 0 ]]; then
        class_args=(--classfiles "$class_dir")
    fi
    java -jar "$CLI_JAR" report "$file_exec" \
        "${class_args[@]}" \
        --sourcefiles "$source_dir" \
        --xml "$OUTPUT_DIR/files/$file_slug.xml"
done
