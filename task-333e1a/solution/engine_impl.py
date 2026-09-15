#!/usr/bin/env python3
"""
UCI chess engine with MTD-bi search, transposition table, and quiescence search.
Uses chess_core.py for move generation and position management.

"""

import sys
from collections import namedtuple
from functools import partial

sys.path.insert(0, '/app')
from chess_core import (
    Position, Move, from_fen, parse_square, render_square,
    initial, pst, piece,
    A1, H1, A8, H8, N, E, S, W,
    MATE_LOWER, MATE_UPPER, can_kill_king
)

print = partial(print, flush=True)

###############################################################################
# Search constants
###############################################################################

QS = 40
QS_A = 140
EVAL_ROUGHNESS = 15

Entry = namedtuple("Entry", "lower upper")


###############################################################################
# Searcher
###############################################################################

class Searcher:
    def __init__(self):
        self.tp_score = {}
        self.tp_move = {}
        self.history = set()
        self.nodes = 0

    def bound(self, pos, gamma, depth, can_null=True):
        self.nodes += 1
        depth = max(depth, 0)

        if pos.score <= -MATE_LOWER:
            return -MATE_UPPER

        entry = self.tp_score.get(
            (pos, depth, can_null), Entry(-MATE_UPPER, MATE_UPPER)
        )
        if entry.lower >= gamma:
            return entry.lower
        if entry.upper < gamma:
            return entry.upper

        if can_null and depth > 0 and pos in self.history:
            return 0

        def moves():
            # Null-move pruning
            if depth > 2 and can_null and abs(pos.score) < 500:
                yield None, -self.bound(
                    pos.rotate(nullmove=True), 1 - gamma, depth - 3
                )

            # Stand pat in quiescence
            if depth == 0:
                yield None, pos.score

            # Killer / hash move
            killer = self.tp_move.get(pos)
            if not killer and depth > 2:
                self.bound(pos, gamma, depth - 3, can_null=False)
                killer = self.tp_move.get(pos)

            val_lower = QS - depth * QS_A

            if killer and pos.value(killer) >= val_lower:
                yield killer, -self.bound(
                    pos.move(killer), 1 - gamma, depth - 1
                )

            # All moves sorted by value
            for val, move in sorted(
                ((pos.value(m), m) for m in pos.gen_moves()), reverse=True
            ):
                if val < val_lower:
                    break
                # Futility pruning
                if depth <= 1 and pos.score + val < gamma:
                    yield move, (
                        pos.score + val if val < MATE_LOWER else MATE_UPPER
                    )
                    break
                yield move, -self.bound(
                    pos.move(move), 1 - gamma, depth - 1
                )

        best = -MATE_UPPER
        for move, score in moves():
            best = max(best, score)
            if best >= gamma:
                if move is not None:
                    self.tp_move[pos] = move
                break

        # Stalemate / checkmate detection
        if depth > 2 and best == -MATE_UPPER:
            flipped = pos.rotate(nullmove=True)
            in_check = self.bound(flipped, MATE_UPPER, 0) == MATE_UPPER
            best = -MATE_LOWER if in_check else 0

        # Update transposition table
        if best >= gamma:
            self.tp_score[pos, depth, can_null] = Entry(best, entry.upper)
        if best < gamma:
            self.tp_score[pos, depth, can_null] = Entry(entry.lower, best)

        return best

    def search(self, history):
        self.nodes = 0
        self.history = set(history)
        self.tp_score.clear()

        gamma = 0
        for depth in range(1, 1000):
            lower, upper = -MATE_LOWER, MATE_LOWER
            while lower < upper - EVAL_ROUGHNESS:
                score = self.bound(
                    history[-1], gamma, depth, can_null=False
                )
                if score >= gamma:
                    lower = score
                if score < gamma:
                    upper = score
                yield depth, gamma, score, self.tp_move.get(history[-1])
                gamma = (lower + upper + 1) // 2


###############################################################################
# UCI protocol
###############################################################################

def main():
    hist = [Position(initial, 0, (True, True), (True, True), 0, 0)]

    while True:
        try:
            line = input().strip()
        except EOFError:
            break
        if not line:
            continue

        args = line.split()

        if args[0] == "uci":
            print("id name SunfishAgent")
            print("id author Agent")
            print("uciok")

        elif args[0] == "isready":
            print("readyok")

        elif args[0] == "quit":
            break

        elif args[:2] == ["position", "startpos"]:
            hist = [Position(initial, 0, (True, True), (True, True), 0, 0)]
            if len(args) > 2 and args[2] == "moves":
                for ply, move_str in enumerate(args[3:]):
                    i = parse_square(move_str[:2])
                    j = parse_square(move_str[2:4])
                    prom = move_str[4:].upper() if len(move_str) > 4 else ""
                    if ply % 2 == 1:
                        i, j = 119 - i, 119 - j
                    hist.append(hist[-1].move(Move(i, j, prom)))

        elif args[:2] == ["position", "fen"]:
            # Find where "moves" keyword is, FEN is everything before it
            fen_end = len(args)
            for idx in range(2, len(args)):
                if args[idx] == "moves":
                    fen_end = idx
                    break
            fen = " ".join(args[2:fen_end])
            pos = from_fen(fen)
            color = args[3]  # 'w' or 'b'
            if color == 'w':
                hist = [pos]
            else:
                hist = [pos.rotate(), pos]

            if fen_end < len(args) and args[fen_end] == "moves":
                for move_str in args[fen_end + 1:]:
                    i = parse_square(move_str[:2])
                    j = parse_square(move_str[2:4])
                    prom = move_str[4:].upper() if len(move_str) > 4 else ""
                    if len(hist) % 2 == 0:
                        i, j = 119 - i, 119 - j
                    hist.append(hist[-1].move(Move(i, j, prom)))

        elif args[0] == "go":
            max_depth = 100
            if "depth" in args:
                di = args.index("depth")
                max_depth = int(args[di + 1])

            move_str = None
            for depth, gamma, score, move in Searcher().search(hist):
                if score >= gamma and move:
                    i, j = move.i, move.j
                    if len(hist) % 2 == 0:
                        i, j = 119 - i, 119 - j
                    move_str = (
                        render_square(i)
                        + render_square(j)
                        + move.prom.lower()
                    )
                    print(f"info depth {depth} score cp {score} pv {move_str}")
                if depth >= max_depth:
                    break

            print(f"bestmove {move_str or '(none)'}")


if __name__ == "__main__":
    main()
