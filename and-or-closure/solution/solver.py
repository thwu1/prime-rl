#!/usr/bin/env python3
"""
AND-OR Closure Size — efficient solver.


Algorithm:
  1. Remove constant bits (always 0 or always 1 across all values).
  2. Group remaining active bits into equivalence classes (same 0/1 column).
  3. Pick one representative per class; build a DAG where edge i->j means
     "in every input value where rep-bit i is set, rep-bit j is also set."
  4. Count order ideals (downward-closed sets) of this DAG.
     - For R <= 22: brute-force enumerate all 2^R subsets.
     - For R > 22: meet-in-the-middle with antichain DP on each half.
"""

import sys
input = sys.stdin.buffer.read().decode()
tokens = input.split()
pos = 0

def rd():
    global pos
    v = tokens[pos]; pos += 1
    return int(v)


def solve_case():
    n = rd()
    values = [rd() for _ in range(n)]

    if n <= 1:
        return n

    values = list(set(values))
    n = len(values)
    if n <= 1:
        return 1

    # Constant-bit analysis
    all_and = values[0]
    all_or  = values[0]
    for v in values[1:]:
        all_and &= v
        all_or  |= v

    active_mask = all_and ^ all_or
    if active_mask == 0:
        return 1  # all values identical after dedup

    # Collect active bit positions
    active_bits = []
    tmp = active_mask
    b = 0
    while tmp:
        if tmp & 1:
            active_bits.append(b)
        tmp >>= 1
        b += 1
    num_active = len(active_bits)

    # Map each value to its active-bit pattern
    pset = set()
    for v in values:
        p = 0
        for i, b in enumerate(active_bits):
            if (v >> b) & 1:
                p |= 1 << i
        pset.add(p)
    unique_patterns = sorted(pset)
    num_pat = len(unique_patterns)

    # Equivalence classes: group active bits by their column
    # (tuple of 0/1 across unique_patterns)
    col_to_rep = {}
    for i in range(num_active):
        col = tuple((p >> i) & 1 for p in unique_patterns)
        if col not in col_to_rep:
            col_to_rep[col] = i
    representatives = sorted(col_to_rep.values())
    R = len(representatives)

    # Build implication mask for each representative
    # implies[ri] has bit rj set iff rep j is implied by rep i
    implies = [0] * R
    for ri in range(R):
        bi = representatives[ri]
        mask = (1 << num_active) - 1
        for p in unique_patterns:
            if (p >> bi) & 1:
                mask &= p
        imp = 0
        for rj in range(R):
            bj = representatives[rj]
            if (mask >> bj) & 1:
                imp |= 1 << rj
        implies[ri] = imp

    # Count order ideals
    if R <= 22:
        return _count_brute(R, implies)
    else:
        return _count_mitm(R, implies)


def _count_brute(R, implies):
    """Enumerate all 2^R subsets; check order-ideal property."""
    count = 0
    for s in range(1 << R):
        ok = True
        for i in range(R):
            if (s >> i) & 1:
                if (implies[i] & s) != implies[i]:
                    ok = False
                    break
        if ok:
            count += 1
    return count


def _count_mitm(R, implies):
    """
    Meet-in-the-middle antichain counting.
    Split R bits into two halves; for each half, enumerate antichains.
    Use an antichain DP on the second half, then aggregate.
    """
    h = R // 2          # first-half size
    sh = R - h          # second-half size
    h_mask  = (1 << h)  - 1
    sh_mask = (1 << sh) - 1

    # --- Implication structures within and across halves ---

    # First-half internal implications
    implies_fh = [implies[i] & h_mask for i in range(h)]

    # Second-half internal implications
    implies_sh = [((implies[h + j]) >> h) & sh_mask for j in range(sh)]

    # Cross: for second-half bit j, required first-half bits
    req_fh = [implies[h + j] & h_mask for j in range(sh)]

    # Cross: for first-half bit i, forced second-half bits
    force_sh = [((implies[i]) >> h) & sh_mask for i in range(h)]

    # Cross: for first-half bit i, which second-half bits does it "go up to"
    # (i.e., second-half bits whose implies include first-half bit i)
    up_sh = [0] * h
    for j in range(sh):
        for i in range(h):
            if (req_fh[j] >> i) & 1:
                up_sh[i] |= 1 << j

    # --- Comparable masks for antichain enumeration ---

    # Second-half: comparable[j] = mask of second-half bits comparable with j
    comp_sh = [0] * sh
    for j in range(sh):
        m = 1 << j
        for k in range(sh):
            if k == j:
                continue
            if (implies_sh[j] >> k) & 1:
                m |= 1 << k
            if (implies_sh[k] >> j) & 1:
                m |= 1 << k
        comp_sh[j] = m

    # Antichain count DP on second half:
    # ac[M] = number of antichains that are subsets of bits in M
    ac = [0] * (1 << sh)
    ac[0] = 1
    for m in range(1, 1 << sh):
        j = m.bit_length() - 1
        without_j = m & ~(1 << j)
        without_comp = without_j & ~comp_sh[j]
        ac[m] = ac[without_j] + ac[without_comp]

    # First-half: comparable masks
    comp_fh = [0] * h
    for i in range(h):
        m = 1 << i
        for k in range(h):
            if k == i:
                continue
            if (implies_fh[i] >> k) & 1:
                m |= 1 << k
            if (implies_fh[k] >> i) & 1:
                m |= 1 << k
        comp_fh[i] = m

    # --- Enumerate first-half antichains recursively ---
    total = 0

    def rec(idx, ac_mask, down_bl, up_bl):
        nonlocal total
        if idx == h:
            blocked = down_bl | up_bl
            free = sh_mask & ~blocked
            total += ac[free]
            return
        # skip bit idx
        rec(idx + 1, ac_mask, down_bl, up_bl)
        # include bit idx (if compatible)
        if (comp_fh[idx] & ac_mask) == 0:
            rec(idx + 1,
                ac_mask | (1 << idx),
                down_bl | force_sh[idx],
                up_bl   | up_sh[idx])

    rec(0, 0, 0, 0)
    return total


# --- main ---
T = rd()
out = []
for _ in range(T):
    out.append(str(solve_case()))
sys.stdout.write("\n".join(out) + "\n")
