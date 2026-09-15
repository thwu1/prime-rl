#!/usr/bin/env python3
"""Solution: reverse-engineer the library, discover relay sowing, solve all
positions, build endgame database, and compute analysis.

Key insight: the engine implements relay (lap) sowing — after distributing
seeds, if the last seed lands in a non-store pit that already had seeds
(count > 1 after drop), pick up ALL seeds and continue sowing.  Repeat until
the last seed lands in the player's store (extra turn) or in a formerly
empty pit (now == 1).  No captures.
"""

import json
import sqlite3
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


def solve(board, side, h, memo=None, best_moves=None):
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
    bm = None
    if side == 0:
        best = -9999
        for m in moves:
            nb, ns = do_move(board, side, m, h)
            v = (nb[h] - nb[size - 1]) if ns == -1 else solve(nb, ns, h, memo, best_moves)
            if v > best:
                best = v; bm = m
    else:
        best = 9999
        for m in moves:
            nb, ns = do_move(board, side, m, h)
            v = (nb[h] - nb[size - 1]) if ns == -1 else solve(nb, ns, h, memo, best_moves)
            if v < best:
                best = v; bm = m
    memo[key] = best
    if best_moves is not None:
        best_moves[key] = bm
    return best


# === Build results.json ===

SOLVE_INITIAL = [(2, 2), (2, 3), (3, 2), (3, 3), (4, 2), (4, 3)]
EVALUATE = [
    {"h": 3, "board": [0, 2, 1, 7, 1, 3, 0, 4], "side": 0},
    {"h": 3, "board": [1, 0, 3, 5, 0, 4, 1, 4], "side": 1},
    {"h": 3, "board": [3, 0, 0, 6, 0, 2, 1, 6], "side": 0},
    {"h": 3, "board": [0, 0, 0, 10, 3, 2, 3, 0], "side": 0},
    {"h": 3, "board": [2, 1, 0, 8, 0, 3, 1, 3], "side": 1},
]

results = {"initial": {}, "positions": []}
for h, s in SOLVE_INITIAL:
    board = tuple([s] * h + [0] + [s] * h + [0])
    val = solve(board, 0, h)
    results["initial"][f"{h}_{s}"] = val
    print(f"Variant({h},{s}) = {val}")

for pos in EVALUATE:
    h = pos["h"]
    board = tuple(pos["board"])
    side = pos["side"]
    val = solve(board, side, h)
    results["positions"].append(val)

with open("/app/results.json", "w") as f:
    json.dump(results, f, indent=2)
print("Wrote /app/results.json")


# === Build endgame.db for (3,3) ===

print("Building endgame database for (3,3)...")
memo_33 = {}
bm_33 = {}
board_33 = tuple([3] * 3 + [0] + [3] * 3 + [0])
solve(board_33, 0, 3, memo_33, bm_33)

conn = sqlite3.connect("/app/endgame.db")
conn.execute("""
    CREATE TABLE endgame (
        board TEXT NOT NULL,
        side INTEGER NOT NULL,
        value INTEGER NOT NULL,
        best_move INTEGER,
        PRIMARY KEY (board, side)
    )
""")
for (board, side), value in memo_33.items():
    board_str = ",".join(map(str, board))
    bm = bm_33.get((board, side))
    conn.execute(
        "INSERT INTO endgame (board, side, value, best_move) VALUES (?, ?, ?, ?)",
        (board_str, side, value, bm),
    )
conn.commit()
conn.close()
print(f"Wrote /app/endgame.db ({len(memo_33)} positions)")


# === Build analysis.json ===

print("Computing analysis...")
analysis = {
    "sweep": {},
    "reachable_3_3": len(memo_33),
    "principal_variation_3_2": [],
}

# Sweep: h in {2,3,4}, s in {1,2,3}
for h in [2, 3, 4]:
    for s in [1, 2, 3]:
        board = tuple([s] * h + [0] + [s] * h + [0])
        val = solve(board, 0, h)
        analysis["sweep"][f"{h}_{s}"] = val
        print(f"  Sweep({h},{s}) = {val}")

# Principal variation for (3,2)
memo_32 = {}
bm_32 = {}
board_32 = tuple([2] * 3 + [0] + [2] * 3 + [0])
solve(board_32, 0, 3, memo_32, bm_32)

board = board_32
side = 0
pv = []
for _ in range(1000):
    key = (board, side)
    if key not in bm_32:
        break
    pit = bm_32[key]
    nb, ns = do_move(board, side, pit, 3)
    pv.append({"side": side, "pit": pit, "board_after": list(nb)})
    if ns == -1:
        break
    board, side = nb, ns
analysis["principal_variation_3_2"] = pv

with open("/app/analysis.json", "w") as f:
    json.dump(analysis, f, indent=2)
print(f"Wrote /app/analysis.json (PV length: {len(pv)})")
