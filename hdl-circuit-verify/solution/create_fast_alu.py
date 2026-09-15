#!/usr/bin/env python3
"""Create the optimized adder and ALU module."""


code = '''\
"""Optimized adder and ALU for miniHDL."""

from hdl import Wire, Bus, mux, const


def fast_adder(a, b, cin):
    """4-bit adder with parallel carry computation.

    Args:
        a: Bus (LSB first)
        b: Bus (LSB first)
        cin: Wire carry-in

    Returns:
        (sum_bus, carry_out): Bus and Wire
    """
    n = len(a)

    # Generate and propagate signals
    g = [a[i] & b[i] for i in range(n)]
    p = [a[i] ^ b[i] for i in range(n)]

    # Parallel carry computation via lookahead equations
    c = [None] * (n + 1)
    c[0] = cin

    # c1 = g0 | (p0 & cin)
    c[1] = g[0] | (p[0] & c[0])

    # c2 = g1 | (p1 & g0) | (p1 & p0 & cin)
    t2_0 = p[1] & g[0]
    t2_1 = (p[1] & p[0]) & c[0]
    c[2] = (g[1] | t2_0) | t2_1

    # c3 = g2 | (p2 & g1) | (p2 & p1 & g0) | (p2 & p1 & p0 & cin)
    t3_0 = p[2] & g[1]
    p2p1 = p[2] & p[1]
    t3_1 = p2p1 & g[0]
    t3_2 = (p2p1 & p[0]) & c[0]
    c[3] = ((g[2] | t3_0) | t3_1) | t3_2

    # c4 = g3 | (p3 & g2) | ... | (p3 & p2 & p1 & p0 & cin)
    t4_0 = p[3] & g[2]
    p3p2 = p[3] & p[2]
    t4_1 = p3p2 & g[1]
    p3p2p1 = p3p2 & p[1]
    t4_2 = p3p2p1 & g[0]
    t4_3 = (p3p2p1 & p[0]) & c[0]
    c[4] = (((g[3] | t4_0) | t4_1) | t4_2) | t4_3

    # Sum = propagate XOR carry-in
    sums = [p[i] ^ c[i] for i in range(n)]

    return Bus(sums), c[n]


def subtractor_fast(a, b):
    """Subtractor using the fast adder (two\\\'s complement)."""
    not_b = ~b
    result, _ = fast_adder(a, not_b, const(1))
    return result


def build_alu_fast(opcode, a, b):
    """ALU using the fast adder for ADD and SUB."""
    res_add, _ = fast_adder(a, b, const(0))
    res_sub    = subtractor_fast(a, b)
    res_and    = a & b
    res_or     = a | b
    res_xor    = a ^ b
    res_not    = ~a

    n = len(a)
    res_shl = Bus([const(0)] + [a[i] for i in range(n - 1)])
    res_shr = Bus([a[i + 1] if i + 1 < n else const(0) for i in range(n)])

    m0 = mux(opcode[0], res_sub, res_add)
    m1 = mux(opcode[0], res_or,  res_and)
    m2 = mux(opcode[0], res_not, res_xor)
    m3 = mux(opcode[0], res_shr, res_shl)

    lo = mux(opcode[1], m1, m0)
    hi = mux(opcode[1], m3, m2)

    return mux(opcode[2], hi, lo)
'''

with open('/app/fast_alu.py', 'w') as f:
    f.write(code)

print("Created fast_alu.py")
