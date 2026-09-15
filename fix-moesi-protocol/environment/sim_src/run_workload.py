#!/usr/bin/env python3
"""
Workload runner for the MOESI cache coherence simulator.

Provides several test workload patterns that exercise different
aspects of the protocol.
"""

import argparse
import json
import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from coherence_sim import CoherenceSimulator, BLOCK_SIZE


def pattern_sequential(sim: CoherenceSimulator, num_accesses: int = 200):
    """Sequential access pattern - tests basic cache behavior."""
    for i in range(num_accesses):
        addr = (i * BLOCK_SIZE) % (256 * 1024)  # 256KB address space
        core = i % sim.num_cores
        data = struct.pack('<Q', i) + b'\x00' * 56
        sim.store(core, addr, data)
        sim.run_until_idle(100)
        sim.load(core, addr)
        sim.run_until_idle(100)


def pattern_writeback_storm(sim: CoherenceSimulator, num_rounds: int = 50):
    """
    Writeback storm pattern - triggers the ILXW→M→MI→I bug.

    Creates a scenario where:
    1. Core 0 gets exclusive line (GETX)
    2. Core 1 also requests exclusive (GETX) - forces writeback from core 0
    3. During the writeback, the L2 is in ILX state fetching from directory
    4. L1 PUTX arrives → L2 goes to ILXW
    5. L1 sends dirty data → L2 goes to M, deallocates dir entry
    6. L2 replacement → MI state → dir sends WB_ACK
    7. WB_ACK handler calls _remove_from_dir → CRASH (already removed)
    """
    base_addrs = list(range(0, 8192, BLOCK_SIZE))  # 128 cache lines

    for round_num in range(num_rounds):
        for line_idx in range(0, len(base_addrs), 2):
            addr = base_addrs[line_idx % len(base_addrs)]
            data = struct.pack('<QQ', round_num, line_idx) + b'\x00' * 48

            # Core 0 writes (gets M state)
            sim.store(0, addr, data)
            sim.run_until_idle(100)

            # Core 1 writes same address (invalidates core 0, core 1 gets M)
            data2 = struct.pack('<QQ', round_num + 1000, line_idx) + b'\x00' * 48
            sim.store(1, addr, data2)
            sim.run_until_idle(100)

            # Core 2 writes to force evictions in L2
            evict_addr = base_addrs[(line_idx + 1) % len(base_addrs)]
            data3 = struct.pack('<QQ', round_num + 2000, line_idx) + b'\x00' * 48
            sim.store(2, evict_addr, data3)
            sim.run_until_idle(100)

            # Core 3 reads to create sharing
            if sim.num_cores > 3:
                sim.load(3, addr)
                sim.run_until_idle(100)

                # Then core 0 writes again (upgrade, more evictions)
                data4 = struct.pack('<QQ', round_num + 3000, line_idx) + b'\x00' * 48
                sim.store(0, addr, data4)
                sim.run_until_idle(100)

    # Force massive eviction cascade
    for i in range(256):
        addr = (i * BLOCK_SIZE + 16384)  # New addresses force evictions
        data = struct.pack('<Q', 0xDEAD0000 + i) + b'\x00' * 56
        sim.store(i % sim.num_cores, addr, data)
        sim.run_until_idle(100)


def analyze_bank_distribution(sim: CoherenceSimulator,
                               num_accesses: int = 1000):
    """Analyze L2 bank distribution with sequential addresses."""
    for i in range(num_accesses):
        addr = i * BLOCK_SIZE
        core = 0
        data = struct.pack('<Q', i) + b'\x00' * 56
        sim.store(core, addr, data)
        sim.run_until_idle(50)

    dist = sim.l2_cache.get_bank_distribution()
    print("\n=== L2 Bank Distribution ===")
    for bank_id, info in dist.items():
        bar = '#' * int(info['percentage'] / 2)
        print(f"  Bank {bank_id}: {info['accesses']:5d} accesses "
              f"({info['percentage']:5.1f}%) {bar}")

    # Calculate standard deviation
    total = sum(info['accesses'] for info in dist.values())
    expected = total / len(dist)
    variance = sum((info['accesses'] - expected) ** 2
                    for info in dist.values()) / len(dist)
    stddev = variance ** 0.5
    cv = stddev / expected if expected > 0 else float('inf')
    print(f"\n  Expected per bank: {expected:.0f}")
    print(f"  Std deviation: {stddev:.1f}")
    print(f"  Coefficient of variation: {cv:.3f}")
    if cv > 0.1:
        print("  WARNING: Bank distribution is severely imbalanced!")
    else:
        print("  OK: Bank distribution is balanced.")
    return cv


def test_dual_memory(sim: CoherenceSimulator, num_accesses: int = 100):
    """Test dual-memory configuration for overlapping ranges."""
    overlaps = sim.mem_system.check_ranges()
    if overlaps:
        print("\n=== Memory Range Overlap Detected ===")
        for r1, r2 in overlaps:
            print(f"  OVERLAP: {r1} and {r2}")

    # Write to addresses near the boundary
    dram_size = 512 * 1024 * 1024
    boundary_addrs = [
        dram_size - 2 * BLOCK_SIZE,
        dram_size - BLOCK_SIZE,
        dram_size,
        dram_size + BLOCK_SIZE,
    ]

    print("\n=== Dual Memory Boundary Test ===")
    duplicate_services = 0
    for addr in boundary_addrs:
        baddr = addr & ~(BLOCK_SIZE - 1)
        controllers = sim.mem_system.get_all_matching_controllers(baddr)
        if len(controllers) > 1:
            print(f"  addr 0x{baddr:x}: served by {len(controllers)} "
                  f"controllers (DUPLICATE)")
            duplicate_services += 1
        else:
            print(f"  addr 0x{baddr:x}: served by 1 controller (OK)")

    if duplicate_services > 0:
        print(f"\n  ERROR: {duplicate_services} addresses served by "
              f"multiple controllers!")
    else:
        print("\n  OK: No duplicate services.")
    return duplicate_services


def main():
    parser = argparse.ArgumentParser(
        description='MOESI Cache Coherence Simulator Workload Runner'
    )
    parser.add_argument('--cores', type=int, default=4,
                        help='Number of cores (default: 4)')
    parser.add_argument('--pattern', type=str, default='sequential',
                        choices=['sequential', 'writeback-storm'],
                        help='Workload pattern')
    parser.add_argument('--analyze-banks', action='store_true',
                        help='Run bank distribution analysis')
    parser.add_argument('--dual-memory', action='store_true',
                        help='Enable dual-memory (DRAM+HBM) mode')
    parser.add_argument('--json-output', type=str,
                        help='Write stats to JSON file')

    args = parser.parse_args()

    num_banks = 4
    sim = CoherenceSimulator(
        num_cores=args.cores,
        num_l2_banks=num_banks,
        dual_memory=args.dual_memory,
    )

    print(f"MOESI Coherence Simulator")
    print(f"  Cores: {args.cores}")
    print(f"  L2 Banks: {num_banks}")
    print(f"  Dual Memory: {args.dual_memory}")
    print(f"  Pattern: {args.pattern}")
    print()

    try:
        if args.analyze_banks:
            analyze_bank_distribution(sim)
        elif args.dual_memory:
            test_dual_memory(sim)
        elif args.pattern == 'sequential':
            pattern_sequential(sim)
            print("Sequential pattern completed successfully.")
        elif args.pattern == 'writeback-storm':
            pattern_writeback_storm(sim)
            print("Writeback storm pattern completed successfully.")

        stats = sim.get_stats()
        print(f"\nSimulation completed in {stats['cycles']} cycles.")

        if args.json_output:
            # Convert sets to lists for JSON serialization
            with open(args.json_output, 'w') as f:
                json.dump(stats, f, indent=2, default=str)
            print(f"Stats written to {args.json_output}")

    except AssertionError as e:
        print(f"\nASSERTION FAILURE: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
