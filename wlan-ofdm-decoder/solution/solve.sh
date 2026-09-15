#!/usr/bin/env bash

# Deploy the solution files to /app
cp /solution/viterbi.c /app/viterbi.c
cp /solution/Makefile /app/Makefile
cp /solution/decoder_impl.py /app/decoder.py

# Build the C shared library
cd /app && make

# Verify it works by running a quick self-test
python3 -c "
import sys
sys.path.insert(0, '/app')
from encoder import encode_frame
from decoder import decode_frame

payload = b'Solution self-test OK'
for mcs in range(8):
    bits, _ = encode_frame(payload, mcs, scrambler_seed=42)
    info, dec = decode_frame(bits, 42)
    assert dec == payload, f'MCS {mcs} failed'
    assert info['mcs'] == mcs
    assert info['length'] == len(payload)
print('All 8 MCS modes decoded successfully via C Viterbi + ctypes.')
"
