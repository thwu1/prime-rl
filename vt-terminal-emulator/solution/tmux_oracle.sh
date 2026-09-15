#!/bin/bash
#
# tmux_oracle.sh -- Use tmux as a reference VT terminal emulator
#
# Usage: ./tmux_oracle.sh WIDTH HEIGHT
# Reads raw bytes from stdin, creates a headless tmux session of the
# specified dimensions, feeds the input to the terminal, captures the
# screen content, and outputs one line per terminal row.

set -euo pipefail

WIDTH="${1:?Usage: tmux_oracle.sh WIDTH HEIGHT}"
HEIGHT="${2:?Usage: tmux_oracle.sh WIDTH HEIGHT}"
SESSION="vtoracle_$$_$(date +%s%N 2>/dev/null || echo $$)"

cleanup() {
    tmux kill-session -t "$SESSION" 2>/dev/null || true
    rm -f "$INPUT_TMP" 2>/dev/null || true
}
trap cleanup EXIT

# Save stdin to a temp file (may contain binary/control characters)
INPUT_TMP=$(mktemp /tmp/oracle_input_XXXXXX)
cat > "$INPUT_TMP"

# Create a headless tmux session with explicit dimensions.
# Run a shell that:
#   1. Disables terminal line discipline processing (raw, no echo, no opost)
#      so escape sequences pass through unmodified
#   2. Clears the screen to remove any shell startup artifacts
#   3. Cats the input file (bytes are interpreted by tmux's VT parser)
#   4. Sleeps to keep the session alive for capture
tmux new-session -d -s "$SESSION" -x "$WIDTH" -y "$HEIGHT" \
    "/bin/sh -c 'stty raw -echo -opost 2>/dev/null; printf \"\\033[2J\\033[H\"; cat \"$INPUT_TMP\"; exec sleep 3600'"

# Give tmux time to process the escape sequences
sleep 0.5

# Capture the pane content (one line per row)
tmux capture-pane -t "$SESSION" -p -S 0 -E "$((HEIGHT - 1))"
