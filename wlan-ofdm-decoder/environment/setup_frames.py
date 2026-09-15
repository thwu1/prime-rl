#!/usr/bin/env python3
"""Generate example WLAN frames for each MCS mode.

Run during Docker build to populate /app/frames/ with test data the
agent can inspect.
"""

import json
import os
import sys

sys.path.insert(0, "/app")
from encoder import encode_frame

FRAME_DIR = "/app/frames"
os.makedirs(FRAME_DIR, exist_ok=True)

# Human-readable payloads (the agent can visually verify their decoder)
PAYLOADS = [
    b"Hello from MCS-0 BPSK rate 1/2!",
    b"MCS-1 test: BPSK with 3/4 coding",
    b"QPSK half-rate frame (MCS 2) here",
    b"MCS3: QPSK three-quarter rate !!",
    b"16-QAM at rate 1/2, this is MCS4",
    b"MCS-5 uses 16QAM with rate 3/4!",
    b"64QAM 2/3 rate => MCS index six!",
    b"And finally MCS7: 64-QAM R=3/4!",
]

manifest = {}

for mcs_idx, payload in enumerate(PAYLOADS):
    seed = 1 + mcs_idx * 17  # deterministic per-MCS seed
    frame_bits, params = encode_frame(payload, mcs_idx, scrambler_seed=seed)

    fname = f"mcs{mcs_idx}.bin"
    fpath = os.path.join(FRAME_DIR, fname)

    # Write one byte per bit (values 0x00 or 0x01)
    with open(fpath, "wb") as f:
        f.write(bytes(frame_bits))

    manifest[fname] = {
        "mcs": mcs_idx,
        "scrambler_seed": seed,
        "n_frame_bits": len(frame_bits),
    }

with open(os.path.join(FRAME_DIR, "manifest.json"), "w") as f:
    json.dump(manifest, f, indent=2)

print(f"Generated {len(PAYLOADS)} example frames in {FRAME_DIR}/")
