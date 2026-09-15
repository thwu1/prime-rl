#!/usr/bin/env python3
"""Post-process solver velocity output to compute flow rates.

Usage: python3 postprocess.py <velocity_file> [H]

Reads a two-column file (y_center, u) and integrates the velocity
to compute the total volumetric flow rate per unit width.
"""

import sys


def read_velocity_data(filepath):
    """Read velocity profile from solver output file."""
    y_vals, u_vals = [], []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) >= 2:
                y_vals.append(float(parts[0]))
                u_vals.append(float(parts[1]))
    return y_vals, u_vals


def compute_flow_rate(y_vals, u_vals, y_start, y_end):
    """Integrate velocity over [y_start, y_end] using cell volumes."""
    if len(y_vals) < 2:
        return 0.0
    dy = y_vals[1] - y_vals[0]  # assumes uniform spacing
    Q = 0.0
    for y, u in zip(y_vals, u_vals):
        y_lo = y - dy / 2
        y_hi = y + dy / 2
        if y_hi <= y_start or y_lo >= y_end:
            continue
        overlap_lo = max(y_lo, y_start)
        overlap_hi = min(y_hi, y_end)
        Q += u * (overlap_hi - overlap_lo)
    return Q


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 postprocess.py <velocity_file> [H]", file=sys.stderr)
        sys.exit(1)

    vel_file = sys.argv[1]
    H = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0

    y, u = read_velocity_data(vel_file)
    Q_total = compute_flow_rate(y, u, 0.0, H)
    print(f"Cells:           {len(y)}")
    print(f"Total flow rate: {Q_total:.6e}")
    print(f"Max velocity:    {max(u):.6e}")
