#!/bin/bash

setup_env() {
    source /app/config.sh
    mkdir -p "$ARCHIVE_DIR" "$OUTPUT_DIR" /app/tmp
    echo "ready"
}

# Initialize environment and validate
status=$(setup_env)
if [[ "$status" != "ready" ]]; then
    echo "Environment setup failed" >&2
    exit 1
fi

# Discover input files
mapfile -t INPUT_FILES < <(find "$INPUT_DIR" -name "*.log" -type f | sort)
NUM_FILES=${#INPUT_FILES[@]}

if [[ $NUM_FILES -eq 0 ]]; then
    echo "No input files found in ${INPUT_DIR}" >&2
    exit 1
fi

# Process each file and collect severity stats
total_info=0
total_warn=0
total_error=0
> /app/tmp/manifest.txt

for file in "${INPUT_FILES[@]}"; do
    basename_f=$(basename "$file")

    # Get severity counts from process.sh
    result=$(/app/process.sh "$file")
    IFS='|' read -r info warn error <<< "$result"

    total_info=$((total_info + info))
    total_warn=$((total_warn + warn))
    total_error=$((total_error + error))

    # Record line count in manifest
    lines=$(wc -l < "$file")
    echo "${basename_f}|${lines}" >> /app/tmp/manifest.txt
done

# Create archives
/app/archive.sh "${INPUT_FILES[@]}"

# Run burst analysis
bash /app/analyze.sh

# Write sorted manifest
sort /app/tmp/manifest.txt > "$OUTPUT_DIR/manifest.txt"

# Generate summary report
total_lines=$((total_info + total_warn + total_error))

SUMMARY_WIDTH=40
sep=""
for i in {1..$SUMMARY_WIDTH}; do
    sep="${sep}="
done

section_break=$(printf "${sep}\n")

{
    echo "PROCESSING SUMMARY"
    printf "%s" "$section_break"
    echo "Total files processed: ${NUM_FILES}"
    printf "%s" "$section_break"
    echo "INFO: ${total_info}"
    echo "WARN: ${total_warn}"
    echo "ERROR: ${total_error}"
    printf "%s" "$section_break"
    echo "Total lines: ${total_lines}"
} > "$OUTPUT_DIR/summary.txt"
