"""Clifford Algebra computation engine matching Uiua's conventions.

Implements blade ordering, metric system, and multivector arithmetic
for arbitrary Clifford algebras Cl(p,q,r).
"""

import math


def mask_tables(dims):
    """Compute Uiua's blade ordering tables.

    Returns (mask_table, inv_mask_table) where:
      mask_table[blade_index] = bitmask
      inv_mask_table[bitmask] = blade_index
    """
    n = 1 << dims
    mask_table = list(range(n))

    # Multi-pass stable sort: for each dimension from highest to lowest,
    # move entries with that bit set to the front.
    for d in range(dims - 1, -1, -1):
        # Stable sort: key -1 for bit set (comes first), key 0 for bit not set
        mask_table.sort(key=lambda a, d=d: -((a >> d) & 1))

    # Final stable sort by grade (number of set bits = popcount)
    mask_table.sort(key=lambda a: bin(a).count("1"))

    # Build inverse table
    inv_mask_table = [0] * n
    for i, v in enumerate(mask_table):
        inv_mask_table[v] = i

    return mask_table, inv_mask_table


def metric(index, p, q, r):
    """Metric value for basis vector at given index under Cl(p,q,r).

    Convention (matching Uiua's Flavor::Cl):
      - First r dimensions (indices 0..r-1) square to 0
      - Next q dimensions (indices r..r+q-1) square to -1
      - Remaining p dimensions square to +1
    """
    if index < r:
        return 0
    index -= r
    if index < q:
        return -1
    return 1


def _blade_grade(mask):
    """Grade of a basis blade given its bitmask."""
    return bin(mask).count("1")


def _blade_product_sign(a_mask, b_mask, dims, p, q, r):
    """Sign and result bitmask for the geometric product of two basis blades.

    Returns (sign, result_mask) where sign is +1, -1, or 0.
    The result bitmask is always a_mask ^ b_mask.
    """
    sign = 1
    for i in range(dims):
        if b_mask & (1 << i):
            # Count bits in a_mask strictly above position i
            higher = a_mask >> (i + 1)
            if bin(higher).count("1") % 2 == 1:
                sign = -sign
            # If bit i is shared (contraction), multiply by metric
            if a_mask & (1 << i):
                m = metric(i, p, q, r)
                if m == 0:
                    return 0, a_mask ^ b_mask
                sign *= m
    return sign, a_mask ^ b_mask


def geo_product(mv_a, mv_b, dims, p, q, r):
    """Geometric (Clifford) product of two multivectors."""
    mt, imt = mask_tables(dims)
    n = 1 << dims
    result = [0.0] * n
    for i in range(n):
        if mv_a[i] == 0:
            continue
        a_mask = mt[i]
        for j in range(n):
            if mv_b[j] == 0:
                continue
            b_mask = mt[j]
            sign, res_mask = _blade_product_sign(a_mask, b_mask, dims, p, q, r)
            if sign != 0:
                result[imt[res_mask]] += sign * mv_a[i] * mv_b[j]
    return result


def outer_product(mv_a, mv_b, dims, p, q, r):
    """Exterior (wedge) product of two multivectors.

    Keeps only terms where result grade = grade(a) + grade(b).
    """
    mt, imt = mask_tables(dims)
    n = 1 << dims
    result = [0.0] * n
    for i in range(n):
        if mv_a[i] == 0:
            continue
        a_mask = mt[i]
        a_grade = _blade_grade(a_mask)
        for j in range(n):
            if mv_b[j] == 0:
                continue
            b_mask = mt[j]
            b_grade = _blade_grade(b_mask)
            sign, res_mask = _blade_product_sign(a_mask, b_mask, dims, p, q, r)
            if sign != 0 and _blade_grade(res_mask) == a_grade + b_grade:
                result[imt[res_mask]] += sign * mv_a[i] * mv_b[j]
    return result


def inner_product(mv_a, mv_b, dims, p, q, r):
    """Left contraction inner product of two multivectors.

    Keeps only terms where result grade = grade(b) - grade(a).
    """
    mt, imt = mask_tables(dims)
    n = 1 << dims
    result = [0.0] * n
    for i in range(n):
        if mv_a[i] == 0:
            continue
        a_mask = mt[i]
        a_grade = _blade_grade(a_mask)
        for j in range(n):
            if mv_b[j] == 0:
                continue
            b_mask = mt[j]
            b_grade = _blade_grade(b_mask)
            sign, res_mask = _blade_product_sign(a_mask, b_mask, dims, p, q, r)
            if sign != 0 and _blade_grade(res_mask) == b_grade - a_grade:
                result[imt[res_mask]] += sign * mv_a[i] * mv_b[j]
    return result


def grade_project(mv, dims, grade):
    """Project a multivector onto a specific grade.

    Returns a new multivector with only grade-k components kept.
    """
    mt, _ = mask_tables(dims)
    n = len(mv)
    result = [0.0] * n
    for i in range(n):
        if _blade_grade(mt[i]) == grade:
            result[i] = mv[i]
    return result


def reverse_mv(mv, dims):
    """Reverse (reversion) of a multivector.

    Each grade-k component is multiplied by (-1)^(k*(k-1)/2).
    """
    mt, _ = mask_tables(dims)
    n = len(mv)
    result = [0.0] * n
    for i in range(n):
        k = _blade_grade(mt[i])
        sign = (-1) ** (k * (k - 1) // 2)
        result[i] = sign * mv[i]
    return result


def sandwich(R, x, dims, p, q, r):
    """Sandwich product: R * x * reverse(R)."""
    Rx = geo_product(R, x, dims, p, q, r)
    R_rev = reverse_mv(R, dims)
    return geo_product(Rx, R_rev, dims, p, q, r)


def exp_bivector(B, dims, p, q, r):
    """Exponential of a simple (rank-1) bivector.

    Handles three cases based on B^2:
      - Elliptic (B^2 < 0): exp(B) = cos(a) + sin(a)/a * B
      - Hyperbolic (B^2 > 0): exp(B) = cosh(a) + sinh(a)/a * B
      - Null (B^2 = 0): exp(B) = 1 + B
    """
    B_sq = geo_product(B, B, dims, p, q, r)
    s = B_sq[0]  # scalar part of B^2

    n = 1 << dims
    result = [0.0] * n

    eps = 1e-12
    if abs(s) < eps:
        # Null case
        result[0] = 1.0
        for i in range(n):
            result[i] += B[i]
    elif s < 0:
        # Elliptic case: B^2 = -alpha^2
        alpha = math.sqrt(-s)
        result[0] = math.cos(alpha)
        scale = math.sin(alpha) / alpha
        for i in range(n):
            result[i] += scale * B[i]
    else:
        # Hyperbolic case: B^2 = +alpha^2
        alpha = math.sqrt(s)
        result[0] = math.cosh(alpha)
        scale = math.sinh(alpha) / alpha
        for i in range(n):
            result[i] += scale * B[i]

    return result
