#!/usr/bin/env python3
"""GPU Shared Memory Bank Conflict Analyzer.

Reads access patterns from /app/patterns.json, analyzes bank conflicts
according to the model in /app/spec.md, and writes results to /app/results.json.
"""


import json

NUM_BANKS = 32
BANK_WIDTH_BYTES = 4
WARP_SIZE = 32


def compute_bank(byte_addr):
    """Compute the bank index for a given byte address."""
    return (byte_addr // BANK_WIDTH_BYTES) % NUM_BANKS


def evaluate_offsets(pattern):
    """Compute 32 byte offsets from a pattern specification.

    Handles both explicit offset lists and formula-based patterns.
    For formulas, evaluates the Python expression with 't' bound to each
    thread index 0..31.
    """
    if "offsets_explicit" in pattern:
        offsets = pattern["offsets_explicit"]
        if len(offsets) != WARP_SIZE:
            raise ValueError(
                f"Expected {WARP_SIZE} offsets, got {len(offsets)}"
            )
        return [int(o) for o in offsets]

    if "offsets_formula" in pattern:
        formula = pattern["offsets_formula"]
        offsets = []
        for t in range(WARP_SIZE):
            offset = eval(formula, {"t": t})
            offsets.append(int(offset))
        return offsets

    raise ValueError("Pattern must have 'offsets_explicit' or 'offsets_formula'")


def analyze_pattern(offsets):
    """Analyze bank conflicts for a set of 32 byte offsets.

    Returns a dict with wavefronts, total_conflicts, and conflict_free.
    Uses sets to track distinct addresses per bank, which naturally handles
    the broadcast rule (duplicate addresses are deduplicated).
    """
    # Map each bank to the set of distinct addresses accessing it
    bank_to_addrs = {}
    for offset in offsets:
        bank = compute_bank(offset)
        if bank not in bank_to_addrs:
            bank_to_addrs[bank] = set()
        bank_to_addrs[bank].add(offset)

    # Compute wavefronts = max distinct addresses across all banks
    wavefronts = 0
    total_conflicts = 0
    for bank_id in range(NUM_BANKS):
        distinct_count = len(bank_to_addrs.get(bank_id, set()))
        if distinct_count > wavefronts:
            wavefronts = distinct_count
        if distinct_count > 1:
            total_conflicts += distinct_count - 1

    # At least 1 wavefront if any accesses exist
    if wavefronts == 0 and len(offsets) > 0:
        wavefronts = 1

    conflict_free = wavefronts <= 1

    return {
        "wavefronts": wavefronts,
        "total_conflicts": total_conflicts,
        "conflict_free": conflict_free,
    }


def main():
    with open("/app/patterns.json") as f:
        data = json.load(f)

    results = {}
    for name, pattern in data["patterns"].items():
        offsets = evaluate_offsets(pattern)
        results[name] = analyze_pattern(offsets)

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Analysis complete. Results written to /app/results.json")
    for name, r in results.items():
        print(
            f"  {name}: wavefronts={r['wavefronts']}, "
            f"conflicts={r['total_conflicts']}, "
            f"conflict_free={r['conflict_free']}"
        )


if __name__ == "__main__":
    main()
