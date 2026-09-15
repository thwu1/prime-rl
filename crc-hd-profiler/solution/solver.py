#!/usr/bin/env python3

"""
CRC Polynomial Hamming Distance Profiler

Computes the Hamming Distance profile for 8-bit CRC polynomials by
enumerating error patterns via GF(2) polynomial arithmetic.

Theory:
- A CRC of width n uses a generator polynomial g(x) of degree n over GF(2).
- An L-bit dataword produces an (L+n)-bit codeword.
- The Hamming Distance (HD) at length L is the minimum Hamming weight of
  any nonzero codeword of length L+n.
- An error pattern E(x) is undetectable iff g(x) divides E(x), i.e.,
  the CRC remainder of E(x) is zero.
- Equivalently, a weight-d error at positions p_0,...,p_{d-1} is
  undetectable iff R[p_0] XOR R[p_1] XOR ... XOR R[p_{d-1}] = 0,
  where R[i] = x^i mod g(x).

Notation:
- Koopman (implicit +1): n-bit value encoding coefficients x^n through x^1,
  with x^0 = 1 implicit. E.g., 0xe7 for degree-8 poly.
- Explicit +1: (n+1)-bit value encoding all coefficients x^n through x^0.
  E.g., 0x1cf.
"""

import json
import sys
from itertools import combinations


def parse_polynomial(poly_spec, width):
    """Parse a polynomial specification and return the explicit+1 integer."""
    notation = poly_spec["notation"]
    value = poly_spec["value"]

    if notation == "koopman":
        koopman = int(value, 16)
        # Koopman encodes x^n..x^1; add implicit x^0 = 1
        return (koopman << 1) | 1

    elif notation == "explicit":
        return int(value, 16)

    elif notation == "algebraic":
        result = 0
        expr = value.replace(" ", "")
        terms = expr.split("+")
        for term in terms:
            if term == "1":
                result |= 1
            elif term == "x":
                result |= (1 << 1)
            elif term.startswith("x^"):
                exp = int(term[2:])
                result |= (1 << exp)
            else:
                raise ValueError(f"Cannot parse term: {term}")
        return result

    else:
        raise ValueError(f"Unknown notation: {notation}")


def explicit_to_koopman(explicit):
    """Convert explicit+1 form to Koopman notation."""
    return explicit >> 1


def compute_remainders(gen_explicit, n, count):
    """
    Compute x^i mod g(x) for i = 0, 1, ..., count-1 using a shift register.

    gen_explicit: the generator polynomial in explicit+1 form (n+1 bits)
    n: CRC width (degree of generator)
    count: number of remainders to compute
    """
    remainders = []
    mask = (1 << n) - 1
    r = 1  # x^0 mod g(x) = 1
    for _ in range(count):
        remainders.append(r)
        # Multiply by x: shift left
        r <<= 1
        # If x^n term present, reduce modulo g(x)
        if r & (1 << n):
            r ^= gen_explicit
        r &= mask
    return remainders


def has_weight2_error(remainders):
    """Check if any two remainders are equal (weight-2 undetectable error)."""
    seen = set()
    for r in remainders:
        if r in seen:
            return True
        seen.add(r)
    return False


def has_weight3_error(remainders):
    """
    Check if R[a] ^ R[b] = R[c] for distinct a, b, c.
    Assumes all remainders are already distinct (HD >= 3 verified).
    """
    N = len(remainders)
    r_set = set(remainders)
    for i in range(N):
        for j in range(i + 1, N):
            v = remainders[i] ^ remainders[j]
            # v can't be 0 (since remainders are distinct)
            # v can't equal R[i] or R[j] (would require the other to be 0)
            if v in r_set:
                return True
    return False


def has_weight4_error(remainders):
    """
    Check if R[a]^R[b]^R[c]^R[d] = 0 for four distinct positions.
    Uses pair-XOR birthday: find two pairs with same XOR and disjoint indices.
    """
    N = len(remainders)
    pair_xors = {}
    for i in range(N):
        for j in range(i + 1, N):
            v = remainders[i] ^ remainders[j]
            if v not in pair_xors:
                pair_xors[v] = []
            pair_xors[v].append((i, j))

    for pairs in pair_xors.values():
        if len(pairs) < 2:
            continue
        for a in range(len(pairs)):
            for b in range(a + 1, len(pairs)):
                i1, j1 = pairs[a]
                i2, j2 = pairs[b]
                if len({i1, j1, i2, j2}) == 4:
                    return True
    return False


def has_weightk_error_bruteforce(remainders, k):
    """
    Brute-force check for weight-k undetectable error.
    Only practical for small codeword lengths (N <= ~30).
    """
    N = len(remainders)
    for combo in combinations(range(N), k):
        xor_val = 0
        for idx in combo:
            xor_val ^= remainders[idx]
        if xor_val == 0:
            return True
    return False


def has_undetectable_error(remainders, weight):
    """Check if an undetectable error of the given weight exists."""
    if weight == 1:
        return 0 in remainders
    if weight == 2:
        return has_weight2_error(remainders)
    if weight == 3:
        return has_weight3_error(remainders)
    if weight == 4:
        return has_weight4_error(remainders)
    # For weight >= 5, use brute force (only at small codeword lengths)
    return has_weightk_error_bruteforce(remainders, weight)


def find_hd_boundary(gen_explicit, n, target_hd, upper_bound):
    """
    Find the maximum dataword length L where HD >= target_hd.

    Binary searches in [1, upper_bound] for the transition point.
    Returns 0 if no L >= 1 achieves this HD.
    """
    if upper_bound < 1:
        return 0

    # Check weight = target_hd - 1 (the critical weight)
    check_weight = target_hd - 1

    lo, hi = 0, upper_bound
    while lo < hi:
        mid = (lo + hi + 1) // 2
        codeword_len = mid + n
        remainders = compute_remainders(gen_explicit, n, codeword_len)
        if not has_undetectable_error(remainders, check_weight):
            lo = mid  # HD >= target_hd at length mid
        else:
            hi = mid - 1
    return lo


def compute_hd_profile(gen_explicit, n, max_dataword):
    """
    Compute the full Hamming Distance profile.

    Returns a list [max_L_at_HD3, max_L_at_HD4, ...] where each entry
    is the maximum dataword length at which the CRC achieves at least
    that Hamming Distance. The list terminates when no L >= 1 achieves
    the next HD level.
    """
    profile = []
    upper = max_dataword
    hd = 3

    while True:
        boundary = find_hd_boundary(gen_explicit, n, hd, upper)
        if boundary < 1:
            break
        profile.append(boundary)
        upper = boundary
        hd += 1

    return profile


def has_odd_parity(gen_explicit):
    """
    Check if g(x) has (x+1) as a factor over GF(2).

    g(1) = sum of all coefficients mod 2. If g(1) = 0, then x=1 is a root,
    meaning (x+1) divides g(x). This is equivalent to the number of set
    bits being even.
    """
    return bin(gen_explicit).count("1") % 2 == 0


def main():
    with open("/app/polynomials.json") as f:
        config = json.load(f)

    width = config["crc_width"]
    max_dw = config["max_dataword_bits"]

    results = {}

    for poly in config["polynomials"]:
        pid = poly["id"]
        gen = parse_polynomial(poly, width)
        koopman = explicit_to_koopman(gen)
        profile = compute_hd_profile(gen, width, max_dw)
        odd_par = has_odd_parity(gen)

        results[pid] = {
            "koopman_hex": hex(koopman),
            "generator_hex": hex(gen),
            "hd_profile": profile,
            "has_odd_parity": odd_par,
        }

        print(f"{pid}: koopman={hex(koopman)}, gen={hex(gen)}, "
              f"profile={profile}, odd_parity={odd_par}")

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
