#!/usr/bin/env python3
"""Generate deterministic cache trace files for the cache simulator task."""
import random
import os


def generate_trace_a(path):
    """500 accesses with temporal locality and conflict patterns."""
    rng = random.Random(0xA1B2C3D4)
    lines = []
    hot_bases = [
        0x10000000, 0x10000020, 0x10000040, 0x10000060,
        0x10000080, 0x100000A0, 0x100000C0, 0x100000E0,
    ]
    cold_bases = [
        0x20000000, 0x20000020, 0x20000040, 0x20000060,
        0x30000000, 0x30000020, 0x30000040, 0x30000060,
        0x40000000, 0x40000020, 0x50000000, 0x50000020,
        0x60000000, 0x60000020, 0x70000000, 0x70000020,
    ]
    for _ in range(500):
        op = 'w' if rng.random() < 0.28 else 'r'
        if rng.random() < 0.65:
            base = rng.choice(hot_bases)
        else:
            base = rng.choice(cold_bases)
        offset = rng.randint(0, 7) * 4
        addr = (base + offset) & 0xFFFFFFFF
        lines.append(f"{op} {addr:08x}")
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


def generate_trace_b(path):
    """1000 accesses with streaming and periodic working set reuse."""
    rng = random.Random(0xDEADBEEF)
    lines = []
    ws_bases = [0xA0000000 + i * 0x40 for i in range(12)]
    stream_base = 0x80000000
    stream_stride = 64
    stream_size = 64 * 1024
    for i in range(1000):
        op = 'w' if rng.random() < 0.22 else 'r'
        if i % 8 < 2:
            base = rng.choice(ws_bases)
        else:
            base = stream_base + ((i * stream_stride) % stream_size)
        offset = rng.randint(0, 15) * 4
        addr = (base + offset) & 0xFFFFFFFF
        lines.append(f"{op} {addr:08x}")
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


def generate_trace_c(path):
    """800 accesses designed to show clear associativity effects.
    Addresses in set0_addrs and set5_addrs all map to the same cache set
    (for a 2048B/32B-block cache), creating heavy conflicts that only
    higher associativity can absorb."""
    rng = random.Random(0xFEEDFACE)
    lines = []
    # 8 addresses all mapping to set 0 in a 2048B/32B direct-mapped cache
    # stride = n_sets * block_size = 64 * 32 = 2048 = 0x800
    set0_addrs = [0xC0000000 + i * 0x800 for i in range(8)]
    # 8 addresses all mapping to set 5
    set5_addrs = [0xC00000A0 + i * 0x800 for i in range(8)]
    # 40 addresses spread across other sets (starting at set 16)
    other_addrs = [0xD0000200 + i * 0x20 for i in range(40)]
    for i in range(800):
        op = 'w' if rng.random() < 0.24 else 'r'
        r = rng.random()
        if r < 0.30:
            base = rng.choice(set0_addrs)
        elif r < 0.50:
            base = rng.choice(set5_addrs)
        else:
            base = rng.choice(other_addrs)
        offset = rng.randint(0, 7) * 4
        addr = (base + offset) & 0xFFFFFFFF
        lines.append(f"{op} {addr:08x}")
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


os.makedirs('/app/traces', exist_ok=True)
generate_trace_a('/app/traces/trace_a.txt')
generate_trace_b('/app/traces/trace_b.txt')
generate_trace_c('/app/traces/trace_c.txt')
print("Traces generated successfully.")
