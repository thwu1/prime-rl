#!/bin/bash
# tmux_oracle.sh -- Use tmux as a reference VT terminal emulator
#
# Usage: ./tmux_oracle.sh WIDTH HEIGHT
# Reads raw bytes from stdin.
# Creates a headless tmux session of the specified dimensions, feeds the
# input bytes to the session so they are processed by tmux's VT parser,
# then captures and prints the screen content (one line per terminal row).
#
# Requirements:
#   - tmux must be installed
#   - The script must handle arbitrary binary input including escape sequences
#   - Escape sequences in the input must be processed by tmux's terminal
#     emulator (not interpreted as keyboard input)
#   - Terminal line discipline (echo, output post-processing) must be
#     configured so raw bytes pass through unmodified
#   - Output: exactly HEIGHT lines to stdout, one per terminal row
#   - Empty/unwritten cells appear as spaces (tmux default)
#   - The tmux session must be cleaned up on exit
#
# TODO: Implement this script

WIDTH="${1:?Usage: tmux_oracle.sh WIDTH HEIGHT}"
HEIGHT="${2:?Usage: tmux_oracle.sh WIDTH HEIGHT}"

# TODO: Create a headless tmux session, feed the raw input bytes to the
#       terminal, capture the pane content, output it, and clean up.
