#!/usr/bin/env python3
"""
Generate a streaming memory trace for the Ramulator 2.0 SimpleO3 frontend.

SimpleO3 trace format: <distance> <address>
where 'distance' is the number of non-memory instructions between
consecutive memory requests, and 'address' is a byte address.
"""

import os

OUTPUT_DIR = "/app/sim_output"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "streaming.trace")
CACHE_LINE_SIZE = 64
NUM_INSTS = 100000
DISTANCE = 10  # Non-memory instructions between memory accesses


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(OUTPUT_FILE, "w") as f:
        addr = 0
        generated = 0
        while generated < NUM_INSTS:
            f.write(f"{DISTANCE} {addr}\n")
            addr += CACHE_LINE_SIZE
            generated += DISTANCE

    num_lines = NUM_INSTS // DISTANCE
    print(f"Generated streaming trace: {OUTPUT_FILE}")
    print(f"  {num_lines} memory requests, {NUM_INSTS} total instructions")


if __name__ == "__main__":
    main()
