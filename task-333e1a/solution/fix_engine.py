#!/usr/bin/env python3
"""
Fix the two bugs in the chess engine by analyzing the code and applying
targeted corrections.

Bug 1 (gen_moves - pawn double move): The condition that prevents pawns
from making double moves when not on the starting rank uses 'and' instead
of 'or'. With 'and', the break only happens when BOTH the pawn is off the
starting rank AND the intermediate square is blocked. It should break when
EITHER condition is true.

Bug 2 (move - castling rook removal): The condition for selecting which
rook to remove during castling has the comparison reversed. When castling
queenside (king moves left, j < i), the A1 rook should be removed. The
buggy code uses 'j > i' which removes the wrong rook.
"""


import sys


def main():
    with open('/app/engine.py', 'r') as f:
        content = f.read()

    original = content

    # Bug 1: In gen_moves(), pawn double-move uses 'and' where it needs 'or'
    # The break should fire when EITHER the pawn is not on the starting rank
    # OR the intermediate square is occupied.
    bug1_old = 'if d == N + N and (i < A1 + N and self.board[i + N] != "."): break'
    bug1_new = 'if d == N + N and (i < A1 + N or self.board[i + N] != "."): break'

    if bug1_old not in content:
        print("WARNING: Bug 1 pattern not found - may already be fixed")
    else:
        content = content.replace(bug1_old, bug1_new)
        print("Fixed Bug 1: pawn double-move condition (and -> or)")

    # Bug 2: In move(), castling rook removal comparison is reversed
    # When castling queenside (j < i), should remove A1 rook.
    # The bug uses j > i, which picks the wrong rook.
    bug2_old = 'board = put(board, A1 if j > i else H1, ".")'
    bug2_new = 'board = put(board, A1 if j < i else H1, ".")'

    if bug2_old not in content:
        print("WARNING: Bug 2 pattern not found - may already be fixed")
    else:
        content = content.replace(bug2_old, bug2_new)
        print("Fixed Bug 2: castling rook removal comparison (> -> <)")

    if content != original:
        with open('/app/engine.py', 'w') as f:
            f.write(content)
        print("\nEngine bugs fixed successfully.")
    else:
        print("\nNo changes made.")

    # Verify by running a quick perft check
    sys.path.insert(0, '/app')
    # Force reimport after edit
    if 'engine' in sys.modules:
        del sys.modules['engine']
    from engine import from_fen, perft

    pos = from_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    result = perft(pos, 3)
    assert result == 8902, f"Verification failed: starting position depth 3 = {result}, expected 8902"
    print(f"Verification passed: starting position depth 3 = {result}")


if __name__ == '__main__':
    main()
