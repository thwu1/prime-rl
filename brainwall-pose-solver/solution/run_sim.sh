#!/bin/bash

set -euo pipefail

TOOLS_DIR="/app/tools"
SIM_DIR="/app/simulator"

# Decode binary formats to JSON using compiled C tools
MODEL_JSON=$("$TOOLS_DIR/mdl2json" "$1")
TRACE_JSON=$("$TOOLS_DIR/nbt2json" "$2")

# Write decoded JSON to temp files for the simulation engine
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT
echo "$MODEL_JSON" > "$TMPDIR/model.json"
echo "$TRACE_JSON" > "$TMPDIR/trace.json"

# Run the simulation engine
python3 "$SIM_DIR/simulate.py" "$TMPDIR/model.json" "$TMPDIR/trace.json"
