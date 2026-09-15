#!/bin/bash
# Batch process CDM files
# Usage: ./run.sh file1.txt file2.txt ...


JAR="/app/target/conjanalysis-1.0.jar"
HBR=${CDM_HBR:-10.0}

for f in "$@"; do
    TMPOUT=$(mktemp /tmp/cdm_result_XXXXXX.json)
    java -jar "$JAR" cdm "$f" "$HBR" "$TMPOUT" 2>/dev/null
    if [ $? -eq 0 ]; then
        cat "$TMPOUT"
    fi
    rm -f "$TMPOUT"
done
