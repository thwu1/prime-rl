#!/usr/bin/env python3
"""Generate game traces using the compiled CLI binary.
Run during Docker build; deleted afterwards."""
import json
import os
import subprocess


def engine(args):
    r = subprocess.run(
        ["/tmp/fairkalah_cli"] + [str(a) for a in args],
        capture_output=True, text=True, timeout=30,
    )
    return r.stdout.strip()


def play_game(h, s, strategy="first"):
    init_csv = engine(["init", h, s])
    board = list(map(int, init_csv.split(",")))
    side = 0
    moves = []
    for _ in range(500):
        csv = ",".join(map(str, board))
        ml = engine(["moves", h, csv, side])
        if not ml:
            break
        legal = list(map(int, ml.split()))
        if not legal:
            break
        pit = legal[0] if strategy == "first" else legal[-1]
        before = list(board)
        result = engine(["play", h, csv, side, pit])
        parts = result.rsplit(" ", 1)
        new_board = list(map(int, parts[0].split(",")))
        ns = int(parts[1])
        moves.append({
            "side": side,
            "board_before": before,
            "pit": pit,
            "board_after": list(new_board),
            "next_side": ns,
        })
        if ns == -1:
            break
        board = new_board
        side = ns
    final = moves[-1]["board_after"] if moves else board
    value = final[h] - final[2 * h + 1]
    return {"h": h, "s": s, "strategy": strategy, "moves": moves, "final_value": value}


os.makedirs("/app/traces", exist_ok=True)

games = [
    play_game(2, 2, "first"),
    play_game(3, 2, "first"),
    play_game(3, 3, "first"),
]
with open("/app/traces/games.json", "w") as f:
    json.dump(games, f, indent=2)
