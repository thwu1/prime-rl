#!/bin/bash
# Counts INFO, WARN, ERROR occurrences in a log file
# Usage: process.sh <logfile>
# Output: INFO_COUNT|WARN_COUNT|ERROR_COUNT

info=0
warn=0
error=0

cat "$1" | while IFS='|' read -r timestamp level message; do
    case "$level" in
        INFO)  ((info++)) ;;
        WARN)  ((warn++)) ;;
        ERROR) ((error++)) ;;
    esac
done

echo "${info}|${warn}|${error}"
