#!/usr/bin/env python3
"""Generate deterministic memory access traces for MESI cache coherence simulation."""

import os
import random


def generate_workload_trace(filepath):
    """Generate main workload trace: 4 cores, 8000 accesses with varied coherence patterns.

    Designed so that cache sizes 512B-4KB have high miss rates (>10%) and
    sizes 8KB+ achieve lower miss rates (<10%), creating a meaningful
    design-space exploration target.
    """
    random.seed(0xCAFEBABE)

    LINE_SIZE = 64

    def align(addr):
        return addr & ~(LINE_SIZE - 1)

    accesses = []

    # Phase 1 (2000 accesses): Private sequential streaming
    # Each core reads/writes its own 2KB region with good temporal locality.
    # Core 0: 0x0000-0x07FF, Core 1: 0x0800-0x0FFF,
    # Core 2: 0x1000-0x17FF, Core 3: 0x1800-0x1FFF
    for i in range(2000):
        core = i % 4
        base = core * 0x0800
        offset = align((i // 4) * 16 % 0x0800)
        addr = base + offset
        op = 'W' if (i % 7 == 0) else 'R'
        accesses.append((core, op, addr))

    # Phase 2 (2000 accesses): Working set reuse with temporal locality
    # Each core repeatedly accesses a hot 1KB subset of its region.
    for i in range(2000):
        core = i % 4
        base = core * 0x0800
        offset = align(random.randint(0, 0x03FF))
        addr = base + offset
        op = 'W' if random.random() < 0.2 else 'R'
        accesses.append((core, op, addr))

    # Phase 3 (2000 accesses): Moderate sharing between cores 0 and 1
    # on a shared 512B region, plus cores 2 and 3 continue private access.
    for i in range(2000):
        core = i % 4
        if core <= 1:
            # Shared region: 0x2000-0x21FF (512B = 8 cache lines)
            addr = 0x2000 + align(random.randint(0, 0x01FF))
            op = 'W' if random.random() < 0.3 else 'R'
        else:
            # Private reuse
            base = core * 0x0800
            offset = align(random.randint(0, 0x07FF))
            addr = base + offset
            op = 'R'
        accesses.append((core, op, addr))

    # Phase 4 (2000 accesses): Mixed realistic workload
    # Cores revisit their private regions with some wider access
    for i in range(2000):
        core = random.randint(0, 3)
        base = core * 0x0800
        if random.random() < 0.7:
            # Hot working set (256B per core)
            offset = align(random.randint(0, 0x00FF))
        else:
            # Occasional wider access within own region
            offset = align(random.randint(0, 0x07FF))
        addr = base + offset
        op = 'W' if random.random() < 0.15 else 'R'
        accesses.append((core, op, addr))

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w') as f:
        for core, op, addr in accesses:
            f.write("{} {} 0x{:08x}\n".format(core, op, addr))


def generate_test_vector_trace(filepath):
    """Generate small test vector: 2 cores, 6 accesses.

    Config for validation: 2 cores, 64B cache, 1-way (direct-mapped), 32B lines -> 2 sets.
    offset_bits=5, index_bits=1, set_index = (addr>>5)&1, tag = addr>>6.

    Hand-traced expected results:
      Core 0: hits=1, misses=3, evictions=1, writebacks=1, inv_recv=0, upgrades=1
      Core 1: hits=0, misses=2, evictions=0, writebacks=0, inv_recv=1, upgrades=0
      Global: total_hits=1, total_misses=5, bus_tx=6, inv=1, mem_reads=5, mem_writes=1
    """
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w') as f:
        f.write("0 R 0x00000000\n")
        f.write("0 R 0x00000020\n")
        f.write("1 R 0x00000000\n")
        f.write("0 W 0x00000000\n")
        f.write("0 R 0x00000040\n")
        f.write("1 R 0x00000000\n")


if __name__ == '__main__':
    generate_workload_trace('/app/traces/workload.trace')
    generate_test_vector_trace('/app/traces/test_vector.trace')
    print("Traces generated successfully.")
