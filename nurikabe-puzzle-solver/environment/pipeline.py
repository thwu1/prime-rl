#!/usr/bin/env python3
"""

Pencil puzzle solution recovery pipeline.
Loads target puzzles from targets.json, attempts to solve them using
ppbench's Puzzle API, and writes results to results.json.

Usage: cd /app && python3 pipeline.py
"""
import json
import sys
import traceback


def main():
    with open('/app/targets.json') as f:
        targets = json.load(f)

    print("Initializing ppbench puzzle engine...")
    try:
        from ppbench.puzzle import Puzzle
    except Exception as e:
        print(f"FATAL: Cannot initialize puzzle engine: {e}", file=sys.stderr)
        traceback.print_exc()
        print("\nThe ppbench puzzle engine requires a JavaScript runtime (pzpr.js).",
              file=sys.stderr)
        print("You may need to install additional dependencies or find an",
              file=sys.stderr)
        print("alternative approach to obtain puzzle solutions.", file=sys.stderr)
        sys.exit(1)

    results = []
    for i, target in enumerate(targets):
        url = target['puzzlink_url']
        print(f"[{i+1}/{len(targets)}] {url[:70]}...")

        try:
            puzzle = Puzzle.from_url(url)
            pid = puzzle.pid

            # Extract grid dimensions from URL
            parts = url.split('?')[1].split('/')
            w, h = int(parts[1]), int(parts[2])

            # Attempt to solve by iterating over grid cells
            moves = []
            for row in range(h):
                for col in range(w):
                    x, y = 2 * col + 1, 2 * row + 1
                    move = f"mouse,left,{x},{y}"
                    puzzle.send_move(move)
                    moves.append(move)

                    violations = puzzle.check()
                    if violations:
                        puzzle.send_move(move)  # toggle undo
                        moves.pop()

                    if puzzle.is_complete():
                        break
                if puzzle.is_complete():
                    break

            solved = puzzle.is_complete()
            results.append({
                'puzzlink_url': url,
                'puzzle_type': pid,
                'solved': solved,
                'moves': moves,
            })
            print(f"  {pid}: {'SOLVED' if solved else 'FAILED'} ({len(moves)} moves)")

        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            traceback.print_exc()
            results.append({
                'puzzlink_url': url,
                'puzzle_type': 'unknown',
                'solved': False,
                'moves': [],
            })

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    n = sum(1 for r in results if r['solved'])
    print(f"\nSolved: {n}/{len(results)}")


if __name__ == '__main__':
    main()
