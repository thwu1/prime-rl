"""Geometric algebra computation engine.

Implements multivector operations with blade ordering and support for
VGA, PGA, and general Cl(p,q,r) metric flavors.
"""


def mask_tables(dims):
    """Compute the blade-ordering mask tables for *dims* dimensions.

    Returns (mask_table, inv_mask_table) where
      mask_table[position] = bitmask
      inv_mask_table[bitmask] = position
    """
    n = 1 << dims
    table = list(range(n))
    for d in range(dims - 1, -1, -1):
        dim_mask = 1 << d
        table.sort(key=lambda a, dm=dim_mask: 0 if (a & dm) else 1)
    table.sort(key=lambda a: bin(a).count("1"))

    inv = [0] * n
    for i, v in enumerate(table):
        inv[v] = i
    return table, inv


def blade_grade(bitmask):
    """Return the grade (popcount) of a basis blade bitmask."""
    return bin(bitmask).count("1")


def reorder_sign(mask_a, mask_b):
    """Sign factor from reordering the product of two basis blades."""
    shifted = mask_a >> 1
    count = 0
    while shifted:
        count += bin(shifted & mask_b).count("1")
        shifted >>= 1
    return 1 if count % 2 == 0 else -1


def metric(flavor, bit_index):
    """Metric value (square of basis vector) for a given flavor and index."""
    if flavor == "VGA":
        return 1
    if flavor == "PGA":
        return 0 if bit_index == 0 else 1
    if isinstance(flavor, (tuple, list)) and flavor[0] == "Cl":
        _, p, q, r = flavor
        if bit_index < r:
            return 0
        idx = bit_index - r
        if idx < q:
            return -1
        return 1
    raise ValueError(f"Unknown flavor: {flavor}")


def _product_core(mv_a, mv_b, dims, flavor, grade_filter):
    """Shared loop for geo / outer / inner products."""
    n = 1 << dims
    table, inv = mask_tables(dims)
    result = [0.0] * n

    for i in range(min(len(mv_a), n)):
        ai = mv_a[i]
        if ai == 0:
            continue
        mi = table[i]
        gi = blade_grade(mi)
        for j in range(min(len(mv_b), n)):
            bj = mv_b[j]
            if bj == 0:
                continue
            mj = table[j]
            gj = blade_grade(mj)

            common = mi & mj
            result_mask = mi ^ mj
            gr = blade_grade(result_mask)

            if not grade_filter(gi, gj, gr):
                continue

            met = 1
            temp = common
            bit = 0
            while temp:
                if temp & 1:
                    m = metric(flavor, bit)
                    if m == 0:
                        met = 0
                        break
                    met *= m
                temp >>= 1
                bit += 1
            if met == 0:
                continue

            sign = reorder_sign(mi, mj)
            result[inv[result_mask]] += sign * met * ai * bj
    return result


def geo_product(mv_a, mv_b, dims, flavor="VGA"):
    """Geometric product of two multivectors."""
    return _product_core(mv_a, mv_b, dims, flavor,
                         lambda gi, gj, gr: True)


def outer_product(mv_a, mv_b, dims, flavor="VGA"):
    """Outer (wedge) product of two multivectors."""
    return _product_core(mv_a, mv_b, dims, flavor,
                         lambda gi, gj, gr: gr == gi + gj)


def inner_product(mv_a, mv_b, dims, flavor="VGA"):
    """Hestenes inner product of two multivectors."""
    return _product_core(mv_a, mv_b, dims, flavor,
                         lambda gi, gj, gr: gi > 0 and gj > 0
                                            and gr == abs(gi - gj))


def reverse_mv(mv, dims):
    """Reverse of a multivector (grade-dependent sign flip)."""
    n = 1 << dims
    table, _ = mask_tables(dims)
    result = [0.0] * n
    for i in range(min(len(mv), n)):
        k = blade_grade(table[i])
        sign = (-1) ** (k * (k - 1) // 2)
        result[i] = sign * mv[i]
    return result


def grade_project(mv, grade, dims):
    """Extract only the components of a specific grade."""
    n = 1 << dims
    table, _ = mask_tables(dims)
    result = [0.0] * n
    for i in range(min(len(mv), n)):
        if blade_grade(table[i]) == grade:
            result[i] = mv[i]
    return result


def sandwich(R, x, dims, flavor="VGA"):
    """Sandwich product: R * x * reverse(R).

    Used for rotations and reflections in geometric algebra.
    """
    R_rev = reverse_mv(R, dims)
    temp = geo_product(R, x, dims, flavor)
    return geo_product(temp, R_rev, dims, flavor)


def grade_involution(mv, dims):
    """Grade involution (main involution): negate all odd-grade components.

    Each component of grade k is multiplied by (-1)^k.
    """
    n = 1 << dims
    table, _ = mask_tables(dims)
    result = [0.0] * n
    for i in range(min(len(mv), n)):
        k = blade_grade(table[i])
        sign = (-1) ** k
        result[i] = sign * mv[i]
    return result
