#!/usr/bin/env python3
"""CLI solver for relay-sowing Mancala variant.

Usage:
    python3 solve.py <h> <board_csv> <side>

Prints the game-theoretic value from South's perspective.
"""

import sys

sys.setrecursionlimit(500000)


def get_moves(board, side, h):
    if side == 0:
        return [i for i in range(h) if board[i] > 0]
    return [i for i in range(h + 1, 2 * h + 1) if board[i] > 0]


def do_move(board, side, pit, h):
    size = 2 * h + 2
    b = list(board)
    ms = h if side == 0 else size - 1
    os_ = size - 1 if side == 0 else h
    seeds = b[pit]
    b[pit] = 0
    pos = pit
    while True:
        for _ in range(seeds):
            pos = (pos + 1) % size
            if pos == os_:
                pos = (pos + 1) % size
            b[pos] += 1
        if pos == ms:
            break
        if b[pos] <= 1:
            break
        seeds = b[pos]
        b[pos] = 0
    se = all(b[i] == 0 for i in range(h))
    ne = all(b[i] == 0 for i in range(h + 1, 2 * h + 1))
    if se or ne:
        for i in range(h):
            b[h] += b[i]; b[i] = 0
        for i in range(h + 1, 2 * h + 1):
            b[size - 1] += b[i]; b[i] = 0
        return tuple(b), -1
    return tuple(b), side if pos == ms else 1 - side


def solve(board, side, h, memo=None):
    if memo is None:
        memo = {}
    size = 2 * h + 2
    se = all(board[i] == 0 for i in range(h))
    ne = all(board[i] == 0 for i in range(h + 1, 2 * h + 1))
    if se or ne:
        return (sum(board[i] for i in range(h + 1))
                - sum(board[i] for i in range(h + 1, size)))
    key = (board, side)
    if key in memo:
        return memo[key]
    moves = get_moves(board, side, h)
    if side == 0:
        best = -9999
        for m in moves:
            nb, ns = do_move(board, side, m, h)
            v = (nb[h] - nb[size - 1]) if ns == -1 else solve(nb, ns, h, memo)
            if v > best:
                best = v
    else:
        best = 9999
        for m in moves:
            nb, ns = do_move(board, side, m, h)
            v = (nb[h] - nb[size - 1]) if ns == -1 else solve(nb, ns, h, memo)
            if v < best:
                best = v
    memo[key] = best
    return best


if __name__ == "__main__":
    h = int(sys.argv[1])
    board = tuple(map(int, sys.argv[2].split(",")))
    side = int(sys.argv[3])
    print(solve(board, side, h))
