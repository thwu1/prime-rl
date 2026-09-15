#!/bin/bash

###############################################################################
# Fix 1: config.sh — replace // "comments" with # comments and add OUTPUT_DIR
#
# In shell, // is a valid path (equivalent to /). When a variable assignment
# line contains // after the value, the shell parses it as:
#   VAR=value  //  rest of line
# This is an assignment scoped to the command "//", not to the current shell.
# After the // command fails, the variable is unset.
###############################################################################
cat > /app/config.sh << 'CONFIGEOF'
#!/bin/bash
INPUT_DIR=/app/input
OUTPUT_DIR=/app/output
ARCHIVE_DIR=/app/output/archive
HEADER_FILE=/app/header.txt
ALERT_THRESHOLD=3
BURST_WINDOW=60
CONFIGEOF

###############################################################################
# Fix 2: process.sh — redirect file instead of piping through cat
#
# In bash, every element of a pipeline runs in a subshell. The pattern
#   cat file | while read ...; do ((var++)); done
# increments var inside a subshell; when the pipeline ends, the subshell
# exits and all variable changes are lost. The fix is:
#   while read ...; do ((var++)); done < file
# which keeps the while loop in the current shell.
###############################################################################
cat > /app/process.sh << 'PROCESSEOF'
#!/bin/bash
info=0
warn=0
error=0

while IFS='|' read -r timestamp level message; do
    case "$level" in
        INFO)  ((info++)) ;;
        WARN)  ((warn++)) ;;
        ERROR) ((error++)) ;;
    esac
done < "$1"

echo "${info}|${warn}|${error}"
PROCESSEOF

###############################################################################
# Fix 3: archive.sh — separate arithmetic increment from redirection
#
# When an external command (like cat) has $((i++)) in its redirection target,
# the shell forks a child process to set up file descriptors before exec'ing
# the command. The arithmetic increment happens in the child, so the parent's
# variable is never modified. Splitting the increment into its own statement
# ensures it runs in the parent shell.
###############################################################################
cat > /app/archive.sh << 'ARCHIVEEOF'
#!/bin/bash
source /app/config.sh

file_num=1
for f in "$@"; do
    cat "$HEADER_FILE" "$f" > "${ARCHIVE_DIR}/${file_num}.txt"
    ((file_num++))
done
ARCHIVEEOF

###############################################################################
# Fix 4-6: pipeline.sh
#
# Bug 4 (source in subshell): setup_env() is called via $(setup_env), which
# runs in a command substitution subshell. All variables set by 'source' inside
# the subshell are lost when the subshell exits. Fix: source config.sh directly
# in the main shell, not inside $().
#
# Bug 5 (brace expansion): {1..$VAR} does not work because brace expansion
# runs before variable expansion. Fix: use a C-style for loop.
#
# Bug 6 (newline stripping): $(printf "...\n") strips the trailing newline
# from the command substitution output, merging separator with next line.
# Fix: use echo directly.
###############################################################################
cat > /app/pipeline.sh << 'PIPEEOF'
#!/bin/bash
source /app/config.sh

mkdir -p "$ARCHIVE_DIR" "$OUTPUT_DIR" /app/tmp

mapfile -t INPUT_FILES < <(find "$INPUT_DIR" -name "*.log" -type f | sort)
NUM_FILES=${#INPUT_FILES[@]}

if [[ $NUM_FILES -eq 0 ]]; then
    echo "No input files found" >&2
    exit 1
fi

total_info=0
total_warn=0
total_error=0
> /app/tmp/manifest.txt

for file in "${INPUT_FILES[@]}"; do
    basename_f=$(basename "$file")
    result=$(/app/process.sh "$file")
    IFS='|' read -r info warn error <<< "$result"
    total_info=$((total_info + info))
    total_warn=$((total_warn + warn))
    total_error=$((total_error + error))
    lines=$(wc -l < "$file")
    echo "${basename_f}|${lines}" >> /app/tmp/manifest.txt
done

/app/archive.sh "${INPUT_FILES[@]}"

bash /app/analyze.sh

sort /app/tmp/manifest.txt > "$OUTPUT_DIR/manifest.txt"

total_lines=$((total_info + total_warn + total_error))

SUMMARY_WIDTH=40
sep=""
for ((i=1; i<=SUMMARY_WIDTH; i++)); do
    sep="${sep}="
done

{
    echo "PROCESSING SUMMARY"
    echo "$sep"
    echo "Total files processed: ${NUM_FILES}"
    echo "$sep"
    echo "INFO: ${total_info}"
    echo "WARN: ${total_warn}"
    echo "ERROR: ${total_error}"
    echo "$sep"
    echo "Total lines: ${total_lines}"
} > "$OUTPUT_DIR/summary.txt"
PIPEEOF

###############################################################################
# Implement: analyze.sh — error burst detection
#
# Collects all ERROR entries from all log files, converts timestamps to epoch
# seconds using date(1), sorts globally, then uses a sliding window to detect
# clusters of ALERT_THRESHOLD+ errors within BURST_WINDOW seconds. Overlapping
# windows are merged into a single burst.
###############################################################################
cat > /app/analyze.sh << 'ANALYZEEOF'
#!/bin/bash
source /app/config.sh
mkdir -p "$OUTPUT_DIR"
output_file="$OUTPUT_DIR/alerts.txt"

# Collect all ERROR entries: epoch|original_timestamp|filename
tmpfile=$(mktemp)
for logfile in "$INPUT_DIR"/*.log; do
    [ -f "$logfile" ] || continue
    bn=$(basename "$logfile")
    while IFS='|' read -r ts level msg; do
        if [[ "$level" == "ERROR" ]]; then
            epoch=$(date -d "$ts" +%s 2>/dev/null)
            [[ -n "$epoch" ]] && echo "${epoch}|${ts}|${bn}"
        fi
    done < "$logfile"
done | sort -t'|' -k1,1n > "$tmpfile"

n=$(wc -l < "$tmpfile")
n=$((n + 0))

if [[ $n -eq 0 ]]; then
    echo "NO_BURSTS" > "$output_file"
    rm -f "$tmpfile"
    exit 0
fi

# Read sorted errors into arrays
mapfile -t sorted_lines < "$tmpfile"
rm -f "$tmpfile"

declare -a epochs origts fnames
for idx in "${!sorted_lines[@]}"; do
    IFS='|' read -r ep ot fn <<< "${sorted_lines[$idx]}"
    epochs[$idx]=$ep
    origts[$idx]=$ot
    fnames[$idx]=$fn
done

# Sliding window burst detection with overlap merging
> "$output_file"
found_burst=0
i=0
while [[ $i -lt $n ]]; do
    # Find rightmost j where epochs[j] - epochs[i] <= BURST_WINDOW
    end_epoch=$((epochs[i] + BURST_WINDOW))
    j=$i
    while [[ $((j + 1)) -lt $n && ${epochs[$((j + 1))]} -le $end_epoch ]]; do
        ((j++))
    done
    count=$((j - i + 1))

    if [[ $count -ge $ALERT_THRESHOLD ]]; then
        found_burst=1
        end=$j

        # Extend for overlapping windows starting from subsequent entries
        k=$((i + 1))
        while [[ $k -le $end ]]; do
            ke=$((epochs[k] + BURST_WINDOW))
            m=$k
            while [[ $((m + 1)) -lt $n && ${epochs[$((m + 1))]} -le $ke ]]; do
                ((m++))
            done
            [[ $m -gt $end ]] && end=$m
            ((k++))
        done

        # Collect unique filenames for this burst
        burst_count=$((end - i + 1))
        file_list=""
        for ((k = i; k <= end; k++)); do
            file_list="${file_list}${fnames[$k]}"$'\n'
        done
        unique_files=$(printf '%s' "$file_list" | sort -u | grep -v '^$' | paste -sd, -)

        echo "BURST|${origts[$i]}|${origts[$end]}|${burst_count}|${unique_files}" >> "$output_file"

        i=$((end + 1))
    else
        ((i++))
    fi
done

if [[ $found_burst -eq 0 ]]; then
    echo "NO_BURSTS" > "$output_file"
fi

exit 0
ANALYZEEOF

chmod +x /app/config.sh /app/pipeline.sh /app/process.sh /app/archive.sh /app/analyze.sh

# Clean previous output and run the fixed pipeline
rm -rf /app/output /app/tmp
bash /app/pipeline.sh
