"""
Verification script for the Nurikabe solver.
Runs the solver on the 5 easiest Nurikabe puzzles from golden_300
and reports results.
"""

import sys
sys.path.insert(0, "/app")

from ppbench import load_dataset
from solver import solve


def main():
    records = load_dataset("golden_300")
    nurikabe = [r for r in records if r["pid"] == "nurikabe"]
    nurikabe.sort(key=lambda r: r["number_required_moves"])

    solved = 0
    total = min(5, len(nurikabe))

    for i in range(total):
        url = nurikabe[i]["puzzlink_url"]
        req_moves = nurikabe[i]["number_required_moves"]
        print(f"Puzzle {i}: req_moves={req_moves}, url={url[:60]}...")
        try:
            puzzle = solve(url)
            if puzzle.is_complete():
                print(f"  -> SOLVED")
                solved += 1
            else:
                violations = puzzle.check()
                print(f"  -> INCOMPLETE, violations: {violations}")
        except Exception as e:
            print(f"  -> ERROR: {e}")

    print(f"\nResults: {solved}/{total} puzzles solved")
    if solved < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
