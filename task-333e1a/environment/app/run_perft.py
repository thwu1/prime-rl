#!/usr/bin/env python3
"""Run perft tests on the chess engine and report results."""

import json
import sys

sys.path.insert(0, '/app')
from engine import from_fen, perft


def main():
    with open('/app/positions.json') as f:
        positions = json.load(f)

    all_pass = True
    for i, test in enumerate(positions):
        fen = test['fen']
        depth = test['depth']
        expected = test['nodes']

        pos = from_fen(fen)
        result = perft(pos, depth)

        status = "PASS" if result == expected else "FAIL"
        if result != expected:
            all_pass = False

        print(f"Test {i+1}: {status} - depth={depth} expected={expected} got={result}")
        print(f"  FEN: {fen}")

    if all_pass:
        print("\nAll tests passed!")
        return 0
    else:
        print("\nSome tests failed!")
        return 1


if __name__ == '__main__':
    sys.exit(main())
