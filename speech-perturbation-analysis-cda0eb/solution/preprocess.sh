#!/bin/bash


set -e

if [ $# -ne 2 ]; then
    echo "Usage: $0 <input_wav> <output_wav>" >&2
    exit 1
fi

INPUT="$1"
OUTPUT="$2"

# Resample to 16kHz, mono, 16-bit PCM
# Apply second-order high-pass at 50 Hz (two cascaded first-order)
# Peak normalize to 0 dBFS
sox "$INPUT" -r 16000 -c 1 -b 16 "$OUTPUT" highpass 50 highpass 50 gain -n
