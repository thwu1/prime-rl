#!/bin/bash
#
# argv_inspector.sh — Prints the exact arguments received, one per line.
# Useful for verifying how systemd (or a tokenizer) splits command lines.
#
# Usage: argv_inspector.sh [args...]
# Output:
#   ARGC: <number of arguments>
#   ARG[0]: <first argument>
#   ARG[1]: <second argument>
#   ...

echo "ARGC: $#"
idx=0
for arg in "$@"; do
    echo "ARG[$idx]: $arg"
    idx=$((idx + 1))
done
