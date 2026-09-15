"""
N-Queens solver using algebraic effect handlers with multi-shot continuations.

Non-deterministic choice and backtracking failure are expressed as algebraic
effects (Choose and Fail). The find_all handler explores every branch by
resuming captured continuations multiple times, collecting all valid placements.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from effects import Choose, Fail, find_all


def _is_safe(placed, new_row):
    """
    Check whether placing a queen at new_row in the next column is safe
    given queens already placed in earlier columns.
    """
    new_col = len(placed)
    for prev_col, prev_row in enumerate(placed):
        if prev_row == new_row:
            return False
        if abs(prev_row - new_row) == new_col - prev_col:
            return False
    return True


def _queens_gen(n):
    """
    Generator-based N-Queens computation using algebraic effects.
    """
    placed = []
    for _col in range(n):
        row = yield Choose(list(range(1, n + 1)))
        if _is_safe(placed, row):
            placed.append(row)
        else:
            yield Fail()
    return list(placed)


def solve_queens(n):
    """
    Solve the N-Queens problem.

    Returns all valid placements as a list of solutions, each solution
    being a list of n row positions (1-indexed, one per column), in
    lexicographic order.
    """
    return find_all(_queens_gen, n)


if __name__ == '__main__':
    for n in (5, 8):
        solutions = solve_queens(n)
        print(f"queens({n}): {len(solutions)} solutions")
        if solutions:
            print(f"first: {','.join(map(str, solutions[0]))}")
        else:
            print("first: none")
