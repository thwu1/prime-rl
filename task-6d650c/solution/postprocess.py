#!/usr/bin/env python3
"""
Convert raw solver output + puzzle map into /app/results.json.

"""
import json


def main():
    with open("/tmp/puzzle_map.json") as f:
        puzzles = json.load(f)

    solutions = []
    with open("/tmp/raw_output.txt") as f:
        for line in f:
            parts = line.strip().split()
            length = int(parts[0])
            moves = " ".join(parts[1:]) if len(parts) > 1 else ""
            solutions.append((length, moves))

    assert len(solutions) == len(puzzles), \
        f"Mismatch: {len(solutions)} solutions vs {len(puzzles)} puzzles"

    results = []
    for tiles, (length, moves) in zip(puzzles, solutions):
        results.append({
            "tiles": tiles,
            "length": length,
            "moves": moves,
        })

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Wrote {len(results)} results to /app/results.json")


if __name__ == "__main__":
    main()
