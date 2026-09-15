"""Utility functions for trace parsing and metric computation."""

import math


def parse_trace(filepath):
    """Parse a memory access trace file.

    Returns list of (pc, address, access_type) tuples.
    Skips empty lines and lines starting with '#'.
    """
    accesses = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            pc = int(parts[0], 16)
            addr = int(parts[1], 16)
            atype = int(parts[2])
            accesses.append((pc, addr, atype))
    return accesses


def geomean(values):
    """Geometric mean of positive values."""
    if not values:
        return 1.0
    log_sum = sum(math.log(max(v, 1e-15)) for v in values)
    return math.exp(log_sum / len(values))
