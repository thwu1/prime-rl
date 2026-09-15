#!/usr/bin/env python3
"""
Parse all benchmark data files under /app/benchmarks/, detect unsolvable
configurations via inversion-parity analysis, and write a clean input
file for the C solver.

"""
import json
import os
import sys


def is_solvable(tiles):
    """Check if a 4x4 sliding tile puzzle configuration is solvable.

    For even-width boards with goal [0,1,...,15] (blank at top-left):
    solvable iff (inversions + blank_row_from_bottom_1indexed) is even.
    """
    non_blank = [t for t in tiles if t != 0]
    inversions = 0
    for i in range(len(non_blank)):
        for j in range(i + 1, len(non_blank)):
            if non_blank[i] > non_blank[j]:
                inversions += 1

    blank_pos = tiles.index(0)
    blank_row_from_top = blank_pos // 4
    blank_row_from_bottom = 4 - blank_row_from_top  # 1-indexed

    return (inversions + blank_row_from_bottom) % 2 == 0


def parse_file(filepath):
    """Parse a puzzle data file, handling multiple formats."""
    puzzles = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            # If first token is non-numeric (e.g. "K01"), skip it
            start = 0
            try:
                int(parts[0])
            except ValueError:
                start = 1
            tiles = []
            for p in parts[start:]:
                try:
                    tiles.append(int(p))
                except ValueError:
                    break
            if len(tiles) == 16:
                puzzles.append(tiles)
    return puzzles


def main():
    benchdir = "/app/benchmarks"
    all_puzzles = []

    for fname in sorted(os.listdir(benchdir)):
        fpath = os.path.join(benchdir, fname)
        if os.path.isfile(fpath):
            parsed = parse_file(fpath)
            all_puzzles.extend(parsed)
            print(f"Parsed {len(parsed)} instances from {fname}", file=sys.stderr)

    solvable = [p for p in all_puzzles if is_solvable(p)]
    unsolvable = [p for p in all_puzzles if not is_solvable(p)]

    print(f"Total: {len(all_puzzles)}, solvable: {len(solvable)}, "
          f"unsolvable: {len(unsolvable)}", file=sys.stderr)

    # Write solver input
    with open("/tmp/solvable_input.txt", "w") as f:
        f.write(f"{len(solvable)}\n")
        for tiles in solvable:
            f.write(" ".join(map(str, tiles)) + "\n")

    # Write tile map for postprocessing
    with open("/tmp/puzzle_map.json", "w") as f:
        json.dump(solvable, f)


if __name__ == "__main__":
    main()
