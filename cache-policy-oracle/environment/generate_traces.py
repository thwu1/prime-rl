#!/usr/bin/env python3
"""Generate deterministic cache access traces for replacement policy evaluation."""

import os
import random


def generate_trace_temporal(filepath, num_accesses=100000, seed=42):
    """Strong temporal locality - small working set, Zipf-like distribution."""
    rng = random.Random(seed)
    working_set = [i * 64 for i in range(200)]  # 200 blocks, sets 0-199
    with open(filepath, 'w') as f:
        for _ in range(num_accesses):
            idx = min(int(rng.paretovariate(1.5)) - 1, 199)
            if idx < 0:
                idx = 0
            addr = working_set[idx]
            pc = ((idx * 7919 + 1) & 0xFFFF) * 4
            atype = rng.choices([0, 1, 2, 3], weights=[70, 15, 10, 5])[0]
            f.write(f"0x{pc:x} 0x{addr:x} {atype}\n")


def generate_trace_scan(filepath, num_accesses=100000, seed=43):
    """Sequential scan through large address space - LRU thrashing pattern."""
    total_blocks = 20000
    block_size = 64
    with open(filepath, 'w') as f:
        for i in range(num_accesses):
            block = i % total_blocks
            addr = block * block_size
            f.write(f"0x1000 0x{addr:x} 0\n")


def generate_trace_mixed(filepath, num_accesses=100000, seed=44,
                         num_sets=256, block_size=64):
    """Mix of hot working set and scan - demonstrates cache pollution.

    Hot blocks (100) in sets 0-99.
    Scan blocks (200) concentrated in sets 0-9, 20 per set.
    This creates direct competition in sets 0-9 where SRRIP protects hot blocks.
    """
    rng = random.Random(seed)

    hot_blocks = [s * block_size for s in range(100)]

    scan_blocks = []
    for s in range(10):
        for k in range(1, 21):
            scan_blocks.append((s + k * num_sets) * block_size)

    scan_pos = 0
    with open(filepath, 'w') as f:
        for _ in range(num_accesses):
            if rng.random() < 0.5:
                addr = rng.choice(hot_blocks)
                pc = 0x2000
            else:
                addr = scan_blocks[scan_pos % len(scan_blocks)]
                scan_pos += 1
                pc = 0x3000
            atype = rng.choices([0, 1, 2, 3], weights=[60, 20, 10, 10])[0]
            f.write(f"0x{pc:x} 0x{addr:x} {atype}\n")


def generate_trace_thrash(filepath, num_accesses=100000, seed=45):
    """Working set slightly larger than cache - cyclic with occasional revisits."""
    rng = random.Random(seed)
    ws_size = 4500  # > 4096 cache blocks
    block_size = 64
    with open(filepath, 'w') as f:
        for i in range(num_accesses):
            if rng.random() < 0.1:
                block = rng.randint(0, min(i % ws_size, 100))
            else:
                block = i % ws_size
            addr = block * block_size
            f.write(f"0x4000 0x{addr:x} 0\n")


def generate_trace_micro(filepath, num_sets=256, block_size=64):
    """Micro-validation trace with analytically known OPT and LRU miss counts.

    20 unique blocks all mapping to set 0 of a 256-set, 16-way cache.
    Phase 1: access all 20 blocks (cold misses).
    Phase 2: re-access blocks 0-11.

    Expected results (16-way set-associative):
      OPT: 20 misses (keeps blocks 0-11 by evicting 12-15 which have no future use)
      LRU: 32 misses (evicts blocks 0-3 in phase 1, then cascading evictions in phase 2)
    """
    stride = num_sets * block_size  # 16384
    with open(filepath, 'w') as f:
        # Phase 1: 20 blocks mapping to set 0
        for i in range(20):
            addr = i * stride
            f.write(f"0x5000 0x{addr:x} 0\n")
        # Phase 2: re-access first 12 blocks
        for i in range(12):
            addr = i * stride
            f.write(f"0x5000 0x{addr:x} 0\n")


def main():
    trace_dir = '/app/traces'
    os.makedirs(trace_dir, exist_ok=True)

    generate_trace_temporal(os.path.join(trace_dir, 'trace_temporal.txt'))
    generate_trace_scan(os.path.join(trace_dir, 'trace_scan.txt'))
    generate_trace_mixed(os.path.join(trace_dir, 'trace_mixed.txt'))
    generate_trace_thrash(os.path.join(trace_dir, 'trace_thrash.txt'))
    generate_trace_micro(os.path.join(trace_dir, 'trace_micro.txt'))

    print(f"Generated traces in {trace_dir}:")
    for f in sorted(os.listdir(trace_dir)):
        path = os.path.join(trace_dir, f)
        lines = sum(1 for _ in open(path))
        print(f"  {f}: {lines} accesses")


if __name__ == '__main__':
    main()
