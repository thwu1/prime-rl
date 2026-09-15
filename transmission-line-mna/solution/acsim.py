#!/usr/bin/env python3
"""
AC circuit simulator — pure Python, standard library only.
Supports R, C, L, V, T (ideal lossless transmission line).
"""

import sys
import math

LINLENTOL = 1e-6

SI_SUFFIXES = [
    ('meg', 1e6), ('gig', 1e9), ('k', 1e3), ('m', 1e-3),
    ('u', 1e-6), ('n', 1e-9), ('p', 1e-12), ('f', 1e-15),
    ('g', 1e9), ('t', 1e12),
]


def parse_value(s):
    """Parse a numeric value with optional SI suffix."""
    s = s.strip().lower()
    try:
        return float(s)
    except ValueError:
        pass
    for suffix, mult in sorted(SI_SUFFIXES, key=lambda x: -len(x[0])):
        if s.endswith(suffix):
            try:
                return float(s[:-len(suffix)]) * mult
            except ValueError:
                continue
    raise ValueError(f"Cannot parse value: {s}")


def parse_netlist(filepath):
    """Parse a netlist file into component lists and AC spec."""
    resistors = []
    vsources = []
    capacitors = []
    inductors = []
    tlines = []
    ac_spec = None
    nodes = set()

    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('*'):
                continue

            if line.lower().startswith('.ac'):
                parts = line.split()
                ac_spec = (parse_value(parts[1]), parse_value(parts[2]),
                           parse_value(parts[3]))
                continue

            tokens = line.split()
            name = tokens[0]
            fc = name[0].upper()

            if fc == 'V':
                np_n, nm_n = int(tokens[1]), int(tokens[2])
                amp = parse_value(tokens[3])
                vsources.append((name, np_n, nm_n, amp))
                for nd in (np_n, nm_n):
                    if nd != 0:
                        nodes.add(nd)

            elif fc == 'R':
                np_n, nm_n = int(tokens[1]), int(tokens[2])
                val = parse_value(tokens[3])
                resistors.append((name, np_n, nm_n, val))
                for nd in (np_n, nm_n):
                    if nd != 0:
                        nodes.add(nd)

            elif fc == 'C':
                np_n, nm_n = int(tokens[1]), int(tokens[2])
                val = parse_value(tokens[3])
                capacitors.append((name, np_n, nm_n, val))
                for nd in (np_n, nm_n):
                    if nd != 0:
                        nodes.add(nd)

            elif fc == 'L':
                np_n, nm_n = int(tokens[1]), int(tokens[2])
                val = parse_value(tokens[3])
                inductors.append((name, np_n, nm_n, val))
                for nd in (np_n, nm_n):
                    if nd != 0:
                        nodes.add(nd)

            elif fc == 'T':
                n1, n2, n3, n4 = (int(tokens[1]), int(tokens[2]),
                                   int(tokens[3]), int(tokens[4]))
                params = {}
                for t in tokens[5:]:
                    if '=' in t:
                        k, v = t.split('=', 1)
                        params[k.lower()] = parse_value(v)
                tlines.append((name, n1, n2, n3, n4,
                               params['z'], params['f'], params['nl']))
                for nd in (n1, n2, n3, n4):
                    if nd != 0:
                        nodes.add(nd)

    return sorted(nodes), vsources, resistors, capacitors, inductors, tlines, ac_spec


def tline_admittance(freq, z0, fref, nl):
    """Two-port admittance parameters for ideal lossless transmission line.

    Computes y11 and y12 with resonance avoidance near quarter-wave multiples.
    """
    td = nl / fref
    lenth = freq * td * 4.0  # electrical length in quarter-waves
    dif = lenth - round(lenth)
    if abs(dif) < LINLENTOL:
        lenth = round(lenth) + (-LINLENTOL if dif < 0 else LINLENTOL)
    lenth *= math.pi / 2.0  # convert to radians
    y12 = complex(0, -1.0 / (z0 * math.sin(lenth)))
    y11 = complex(0, -1.0 / (z0 * math.tan(lenth)))
    return y11, y12


def solve_complex(A, b):
    """Solve complex linear system A*x = b via Gaussian elimination
    with partial pivoting."""
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]

    for col in range(n):
        max_val, max_row = 0, col
        for row in range(col, n):
            if abs(M[row][col]) > max_val:
                max_val = abs(M[row][col])
                max_row = row
        M[col], M[max_row] = M[max_row], M[col]

        pivot = M[col][col]
        for row in range(col + 1, n):
            factor = M[row][col] / pivot
            for j in range(col, n + 1):
                M[row][j] -= factor * M[col][j]

    x = [complex(0)] * n
    for i in range(n - 1, -1, -1):
        s = M[i][n]
        for j in range(i + 1, n):
            s -= M[i][j] * x[j]
        x[i] = s / M[i][i]
    return x


def stamp_admittance(A, node_idx, np_n, nm_n, y):
    """Stamp a two-terminal admittance element into the MNA matrix."""
    ip = node_idx.get(np_n, -1)
    im = node_idx.get(nm_n, -1)
    if ip >= 0:
        A[ip][ip] += y
    if im >= 0:
        A[im][im] += y
    if ip >= 0 and im >= 0:
        A[ip][im] -= y
        A[im][ip] -= y


def solve_ac(nodes, vsources, resistors, capacitors, inductors, tlines, freq):
    """Build and solve the MNA system at a given frequency."""
    omega = 2 * math.pi * freq
    n = len(nodes)
    n_extra = len(vsources) + len(inductors)
    sz = n + n_extra
    node_idx = {nd: i for i, nd in enumerate(nodes)}

    A = [[complex(0)] * sz for _ in range(sz)]
    b = [complex(0)] * sz

    # Resistors: real conductance stamp
    for _, np_n, nm_n, val in resistors:
        stamp_admittance(A, node_idx, np_n, nm_n, 1.0 / val)

    # Capacitors: admittance Y = j*omega*C
    for _, np_n, nm_n, val in capacitors:
        stamp_admittance(A, node_idx, np_n, nm_n, complex(0, omega * val))

    # Transmission lines: 4-terminal y-parameter stamp
    for _, n1, n2, n3, n4, z0, fref, nl in tlines:
        y11, y12 = tline_admittance(freq, z0, fref, nl)
        port1 = [(n1, 1), (n2, -1)]
        port2 = [(n3, 1), (n4, -1)]
        for row_t, col_t, yval in [(port1, port1, y11), (port2, port2, y11),
                                    (port1, port2, y12), (port2, port1, y12)]:
            for nd_r, sr in row_t:
                ir = node_idx.get(nd_r, -1)
                for nd_c, sc in col_t:
                    ic = node_idx.get(nd_c, -1)
                    if ir >= 0 and ic >= 0:
                        A[ir][ic] += yval * sr * sc

    # Voltage sources: augmented rows/columns
    for vi, (_, np_n, nm_n, amp) in enumerate(vsources):
        row = n + vi
        ip = node_idx.get(np_n, -1)
        im = node_idx.get(nm_n, -1)
        if ip >= 0:
            A[row][ip] = 1
            A[ip][row] = 1
        if im >= 0:
            A[row][im] = -1
            A[im][row] = -1
        b[row] = amp

    # Inductors: V(n+) - V(n-) = j*omega*L * I_L
    # Augmented row: V(n+) - V(n-) - j*omega*L * I_L = 0
    for li, (_, np_n, nm_n, val) in enumerate(inductors):
        row = n + len(vsources) + li
        ip = node_idx.get(np_n, -1)
        im = node_idx.get(nm_n, -1)
        impedance = complex(0, omega * val)
        if ip >= 0:
            A[row][ip] = 1
            A[ip][row] = 1
        if im >= 0:
            A[row][im] = -1
            A[im][row] = -1
        A[row][row] = -impedance
        b[row] = 0

    x = solve_complex(A, b)
    return [abs(x[i]) for i in range(n)]


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 acsim.py <netlist_file>", file=sys.stderr)
        sys.exit(1)

    nodes, vsources, resistors, capacitors, inductors, tlines, ac_spec = \
        parse_netlist(sys.argv[1])
    if ac_spec is None:
        print("Error: No .ac specification found", file=sys.stderr)
        sys.exit(1)

    fstart, fstop, fstep = ac_spec

    print("#Freq\t" + "\t".join(f"v({n})" for n in nodes))

    freq = fstart
    while freq <= fstop + fstep * 0.001:
        mags = solve_ac(nodes, vsources, resistors, capacitors, inductors,
                        tlines, freq)
        print(f"{freq}" + "".join(f"\t{m:.5g}" for m in mags))
        freq += fstep


if __name__ == "__main__":
    main()
