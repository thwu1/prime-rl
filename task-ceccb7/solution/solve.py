#!/usr/bin/env python3
"""
CRC Polynomial Hamming Distance Analyzer

Computes HD profiles, algebraic properties, and notation conversions for
CRC polynomials given in Koopman (implicit +1) notation.
"""

import json
import sqlite3


def koopman_to_explicit(k, width):
    """Convert Koopman notation to explicit +1 notation."""
    return (k << 1) | 1


def compute_reciprocal_koopman(k, width):
    """Compute the reciprocal polynomial in Koopman notation.

    1. Get explicit +1 form (width+1 bits)
    2. Bit-reverse those width+1 bits
    3. Convert back to Koopman by dropping the LSB
    """
    e = koopman_to_explicit(k, width)
    rev = 0
    for i in range(width + 1):
        if e & (1 << i):
            rev |= (1 << (width - i))
    return rev >> 1


def check_x_plus_1_factor(k, width):
    """G(x) has (x+1) as factor iff G(1) = 0 over GF(2),
    i.e., the number of terms (1-bits in explicit form) is even."""
    e = koopman_to_explicit(k, width)
    return bin(e).count('1') % 2 == 0


def compute_syndromes(gen_explicit, width, count):
    """Compute S(i) = x^i mod G(x) for i = 0, 1, ..., count-1.

    Uses a linear-feedback shift register (LFSR) simulation.
    """
    syns = []
    s = 1  # x^0 mod G(x) = 1
    for _ in range(count):
        syns.append(s)
        s <<= 1
        if s & (1 << width):
            s ^= gen_explicit  # reduce modulo G(x)
    return syns


def check_primitive(k, width):
    """A polynomial of degree n is primitive over GF(2) iff
    the multiplicative order of x mod G(x) equals 2^n - 1."""
    e = koopman_to_explicit(k, width)
    period = (1 << width) - 1  # 2^n - 1

    syns = compute_syndromes(e, width, period + 1)

    # x^period must equal 1
    if syns[period] != 1:
        return False

    # Factor period and check sub-periods
    n = period
    factors = set()
    temp = n
    d = 2
    while d * d <= temp:
        while temp % d == 0:
            factors.add(d)
            temp //= d
        d += 1
    if temp > 1:
        factors.add(temp)

    for p in factors:
        if syns[period // p] == 1:
            return False

    return True


def compute_hd_profile(k, width, max_dw, max_hd):
    """Compute the Hamming Distance profile for a CRC polynomial."""
    e = koopman_to_explicit(k, width)
    max_cw = max_dw + width
    syns = compute_syndromes(e, width, max_cw)

    # HD >= 3: first syndrome collision (2-bit undetected error)
    seen = {}
    hd3_cw = max_cw
    for i in range(max_cw):
        if syns[i] in seen:
            hd3_cw = i
            break
        seen[syns[i]] = i

    hd_cw = {3: hd3_cw}

    # HD >= 4: first 3-bit undetected error (pair XOR match)
    if max_hd >= 4:
        pair_xors = set()
        lim = min(hd3_cw, max_cw)
        hd4_cw = lim
        for i in range(lim):
            if syns[i] in pair_xors:
                hd4_cw = i
                break
            for j in range(i):
                pair_xors.add(syns[i] ^ syns[j])
        hd_cw[4] = hd4_cw

    # HD >= 5: first 4-bit undetected error (triple XOR match)
    if max_hd >= 5:
        triple_xors = set()
        lim = min(hd_cw[4], max_cw)
        hd5_cw = lim
        for i in range(lim):
            if syns[i] in triple_xors:
                hd5_cw = i
                break
            for j in range(i):
                xij = syns[i] ^ syns[j]
                for ki in range(j):
                    triple_xors.add(xij ^ syns[ki])
        hd_cw[5] = hd5_cw

    # HD >= 6: first 5-bit undetected error (quad XOR match)
    if max_hd >= 6:
        quad_xors = set()
        lim = min(hd_cw[5], max_cw)
        hd6_cw = lim
        for i in range(lim):
            if syns[i] in quad_xors:
                hd6_cw = i
                break
            for j in range(i):
                xij = syns[i] ^ syns[j]
                for ki in range(j):
                    xijk = xij ^ syns[ki]
                    for li in range(ki):
                        quad_xors.add(xijk ^ syns[li])
        hd_cw[6] = hd6_cw

    # HD >= 7: first 6-bit undetected error (quint XOR match)
    if max_hd >= 7:
        quint_xors = set()
        lim = min(hd_cw[6], max_cw)
        hd7_cw = lim
        for i in range(lim):
            if syns[i] in quint_xors:
                hd7_cw = i
                break
            for j in range(i):
                xij = syns[i] ^ syns[j]
                for ki in range(j):
                    xijk = xij ^ syns[ki]
                    for li in range(ki):
                        xijkl = xijk ^ syns[li]
                        for mi in range(li):
                            quint_xors.add(xijkl ^ syns[mi])
        hd_cw[7] = hd7_cw

    # HD >= 8: first 7-bit undetected error (sext XOR match)
    if max_hd >= 8:
        sext_xors = set()
        lim = min(hd_cw.get(7, max_cw), max_cw)
        hd8_cw = lim
        for i in range(lim):
            if syns[i] in sext_xors:
                hd8_cw = i
                break
            for j in range(i):
                xij = syns[i] ^ syns[j]
                for ki in range(j):
                    xijk = xij ^ syns[ki]
                    for li in range(ki):
                        xijkl = xijk ^ syns[li]
                        for mi in range(li):
                            xijklm = xijkl ^ syns[mi]
                            for ni in range(mi):
                                sext_xors.add(xijklm ^ syns[ni])
        hd_cw[8] = hd8_cw

    # Build profile: list of max dataword lengths per HD level
    profile = []
    for d in range(3, max_hd + 1):
        if d not in hd_cw:
            break
        mdw = hd_cw[d] - width
        if mdw < 1:
            break
        profile.append(mdw)

    return profile


def achieved_hd(profile, target_len):
    """Determine the Hamming Distance achieved at a given dataword length."""
    hd = 2  # baseline: CRC always detects single-bit errors
    for i, max_len in enumerate(profile):
        if target_len <= max_len:
            hd = i + 3  # profile starts at HD=3
        else:
            break
    return hd


def main():
    # Read configuration from SQLite database
    conn = sqlite3.connect('/app/crc_config.db')
    c = conn.cursor()

    c.execute("SELECT value FROM config WHERE key='crc_width'")
    width = int(c.fetchone()[0])
    c.execute("SELECT value FROM config WHERE key='max_dataword_length'")
    max_dw = int(c.fetchone()[0])
    c.execute("SELECT value FROM config WHERE key='max_hd_check'")
    max_hd = int(c.fetchone()[0])

    c.execute("SELECT koopman_hex FROM polynomials ORDER BY id")
    polys = [row[0] for row in c.fetchall()]

    c.execute("SELECT name, dataword_bits, min_hd FROM scenarios ORDER BY id")
    scenarios = [{'name': r[0], 'dataword_bits': r[1], 'min_hd': r[2]}
                 for r in c.fetchall()]

    conn.close()

    results = {"polynomials": {}, "scenarios": {}}
    profiles = {}

    for ps in polys:
        k = int(ps, 16)

        ep1 = koopman_to_explicit(k, width)
        rk = compute_reciprocal_koopman(k, width)
        prim = check_primitive(k, width)
        x1f = check_x_plus_1_factor(k, width)
        prof = compute_hd_profile(k, width, max_dw, max_hd)

        results["polynomials"][ps] = {
            "explicit_plus_1": hex(ep1),
            "reciprocal_koopman": hex(rk),
            "is_primitive": prim,
            "has_x_plus_1_factor": x1f,
            "hd_profile": prof,
        }
        profiles[ps] = prof

    for sc in scenarios:
        name = sc['name']
        target_len = sc['dataword_bits']
        min_hd = sc['min_hd']

        evals = {}
        qualifying = []
        for ps in polys:
            prof = profiles[ps]
            ahd = achieved_hd(prof, target_len)
            meets = ahd >= min_hd
            evals[ps] = {"achieved_hd": ahd, "meets_requirement": meets}
            if meets:
                idx = ahd - 3
                margin = prof[idx] - target_len if idx < len(prof) else 0
                qualifying.append((ps, ahd, margin, int(ps, 16)))

        # Sort: highest HD, largest margin, smallest polynomial value
        qualifying.sort(key=lambda x: (-x[1], -x[2], x[3]))
        best = qualifying[0][0] if qualifying else None

        results["scenarios"][name] = {
            "evaluations": evals,
            "best_polynomial": best,
        }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)


if __name__ == '__main__':
    main()
