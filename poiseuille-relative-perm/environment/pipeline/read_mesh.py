#!/usr/bin/env python3
"""Read a Gmsh MSH 2.2 file and print node x-coordinates, one per line.

Usage: python3 read_mesh.py <file.msh>

Outputs sorted node x-coordinates to stdout, suitable for piping into
the Octave solver or reading from a file.
"""

import sys


def read_msh2(filename):
    """Parse Gmsh MSH format 2.2 and extract node x-coordinates."""
    coords = []
    with open(filename) as f:
        in_nodes = False
        n_remaining = 0
        for line in f:
            line = line.strip()
            if line == '$Nodes':
                in_nodes = True
                continue
            if line == '$EndNodes':
                break
            if in_nodes:
                if n_remaining == 0:
                    n_remaining = int(line)
                else:
                    parts = line.split()
                    coords.append(float(parts[1]))  # x-coordinate
                    n_remaining -= 1
    return sorted(coords)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 read_mesh.py <file.msh>", file=sys.stderr)
        sys.exit(1)
    coords = read_msh2(sys.argv[1])
    for c in coords:
        print(f"{c:.15e}")
