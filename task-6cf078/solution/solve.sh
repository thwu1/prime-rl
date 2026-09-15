#!/usr/bin/env bash

set -euo pipefail

cd /app

# Build the C reference decoder
make -C /app/libcobs/

# Run C decoder to produce ground truth JSON
/app/libcobs/decode_capture /app/capture.bin > /tmp/c_decoder_output.json 2>/tmp/c_decoder_stderr.txt

# Run the solution Python decoder (produces all output files)
python3 /solution/decoder.py

echo "Solution complete. Results written to /app/results/"
