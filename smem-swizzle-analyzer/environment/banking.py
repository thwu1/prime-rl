"""CUDA shared memory bank conflict simulation.

CUDA shared memory is organized into 32 banks, each 4 bytes wide.
Consecutive 4-byte words map to consecutive banks in round-robin fashion:
  bank_id = (byte_address // 4) % 32

When multiple threads in a warp access different addresses that map to the
same bank, the accesses are serialized. The number of serialization rounds
equals the maximum number of threads hitting any single bank.
"""

from collections import Counter

NUM_BANKS = 32
BANK_WIDTH = 4  # bytes


def compute_bank_id(byte_address):
    """Map a byte address to its shared memory bank index (0..31)."""
    return (byte_address // BANK_WIDTH) % NUM_BANKS


def count_bank_conflicts(byte_addresses):
    """Return conflict severity for a warp access pattern.

    Given a list of byte addresses (one per thread, typically 32),
    returns the number of serialization rounds needed:
      - 0 if no addresses (empty warp)
      - 1 if conflict-free (all threads hit distinct banks)
      - N if the most-loaded bank has N threads hitting it

    Args:
        byte_addresses: list of byte addresses accessed by warp threads

    Returns:
        int: serialization rounds (max threads per bank)
    """
    if not byte_addresses:
        return 0

    bank_ids = [compute_bank_id(a) for a in byte_addresses]
    counts = Counter(bank_ids)

    # Compute the aggregate serialization penalty across all banks
    conflict_total = sum(c - 1 for c in counts.values() if c > 1)
    return conflict_total if conflict_total > 0 else 1
