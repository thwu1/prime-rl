"""Signature-based Hit Prediction (SHiP) replacement policy.

Algorithm specification
=======================

SHiP uses the program counter (PC) as a "signature" to predict whether
incoming cache blocks will be re-referenced. The key insight from the CRC-2
championship is that blocks loaded by the same PC instruction tend to have
similar reuse behaviour.

Data structures
---------------
1. Per-way RRPV values: 3-bit Re-Reference Prediction Value per way per set
   (same as SRRIP). Initialize all to max_rrpv.
2. Per-way signature storage: records which PC signature brought in each
   cache block. Initialize to -1 (invalid).
3. Per-way validity tracking: tracks whether a way has been filled at least
   once (needed to avoid decrementing SHCT on cold fills). Initialize False.
4. Signature Hit Counter Table (SHCT): a table of 2^14 = 16384 entries,
   each a 3-bit saturating counter (range 0-7). Indexed by the PC signature.
   Initialize all entries to 0.

PC signature computation
------------------------
    signature = (pc >> 2) & 0x3FFF

This yields a 14-bit index into the SHCT.

On cache HIT at (set_idx, way) with program counter pc:
    1. Set RRPV[set_idx][way] = 0  (promote to most-recently-used)
    2. Let old_sig = signature[set_idx][way]
    3. If old_sig is valid (>= 0): increment SHCT[old_sig], saturating at 7
       (This signature produced a block that was re-referenced — cache-friendly)

On cache MISS (insertion) at (set_idx, victim_way) with program counter pc:
    1. If victim way was previously valid (way_valid[set_idx][victim_way]):
       decrement SHCT[signature[set_idx][victim_way]], saturating at 0
       (The evicted block's signature produced a block NOT re-referenced — cache-averse)
    2. Record new block's signature: signature[set_idx][victim_way] = pc_signature
    3. Mark way as valid: way_valid[set_idx][victim_way] = True
    4. Determine insertion RRPV:
       - If SHCT[pc_signature] == 0: RRPV = max_rrpv  (distant prediction — likely scan)
       - Else: RRPV = max_rrpv - 1  (intermediate prediction — likely re-referenced)

Victim selection (same as SRRIP):
    1. Look for a way with RRPV >= max_rrpv; return the first one found
    2. If none found, increment all RRPV values in the set by 1 and retry

Storage budget:
    - RRPV bits:      num_sets * num_ways * rrpv_bits
    - Signature bits:  num_sets * num_ways * shct_bits  (14 bits per way)
    - SHCT bits:       2^shct_bits * rrpv_bits          (3-bit counters)
    - Total bytes:     ceil(total_bits / 8)

For 256 sets, 16 ways, 3-bit RRPV, 14-bit signatures:
    (256*16*3 + 256*16*14 + 16384*3 + 7) // 8 = 14848 bytes
"""

from policies.base import ReplacementPolicy


class SHiPPolicy(ReplacementPolicy):
    """Signature-based Hit Prediction.

    Implement according to the specification above.
    """

    def __init__(self, num_sets, num_ways, rrpv_bits=3, shct_bits=14):
        # TODO: Initialize all data structures described in the specification
        raise NotImplementedError("SHiP policy not yet implemented")

    def on_access(self, set_idx, way, hit, pc=0):
        """Update replacement state on hit or miss."""
        raise NotImplementedError

    def find_victim(self, set_idx, cache_set):
        """Select victim way (same as SRRIP)."""
        raise NotImplementedError

    def storage_bytes(self):
        """Compute total auxiliary storage budget in bytes."""
        raise NotImplementedError
