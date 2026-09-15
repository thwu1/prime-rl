"""CUDA shared memory bank conflict analysis.

Shared memory is organized into 32 banks. Each bank is 4 bytes wide.
Consecutive 4-byte words map to consecutive banks in round-robin fashion.

When multiple threads in a warp access different addresses in the same bank,
the accesses are serialized (bank conflict). The severity of a bank conflict
is determined by the maximum number of threads that must access the same bank.
"""

from collections import Counter


def compute_bank_id(byte_address, num_banks=32, bank_width=4):
    """Compute which shared memory bank a byte address maps to.

    Banks are assigned round-robin to consecutive bank_width-byte words.

    Args:
        byte_address: Address in bytes within shared memory
        num_banks: Number of shared memory banks (default 32)
        bank_width: Width of each bank in bytes (default 4)

    Returns:
        Bank index (0 to num_banks-1)
    """
    return (byte_address // bank_width) % num_banks


def count_bank_conflicts(byte_addresses, num_banks=32, bank_width=4):
    """Count bank conflict severity for a warp access pattern.

    Given a list of byte addresses accessed simultaneously by threads in
    a warp, returns the number of serialization rounds needed.

    A conflict-free access (all threads hit different banks) returns 1.
    An N-way conflict (N threads hitting the same bank) returns N.

    Args:
        byte_addresses: List of byte addresses (one per thread, typically 32)
        num_banks: Number of shared memory banks (default 32)
        bank_width: Width of each bank in bytes (default 4)

    Returns:
        Number of serialization rounds (max threads hitting any single bank)
    """
    if not byte_addresses:
        return 0

    bank_ids = [compute_bank_id(addr, num_banks, bank_width)
                for addr in byte_addresses]
    bank_counts = Counter(bank_ids)

    # Count total excess accesses summed across all conflicting banks
    total_conflicts = sum(count - 1 for count in bank_counts.values()
                          if count > 1)
    return total_conflicts if total_conflicts > 0 else 1
