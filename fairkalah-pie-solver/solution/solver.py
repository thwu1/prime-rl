#!/usr/bin/env python3
"""
FairKalah Retrograde Solver Pipeline.
Uses C library via ctypes for state operations, SQLite for endgame database.
"""

import ctypes
import sqlite3
import json
import os
import sys

sys.setrecursionlimit(500000)

# ---------------------------------------------------------------------------
# ctypes bindings for the compiled C library
# ---------------------------------------------------------------------------

lib = ctypes.CDLL("/app/libkalah.so")

MAX_BOARD_SIZE = 18  # 2 * (MAX_PITS + 1), MAX_PITS=8


class CKalahState(ctypes.Structure):
    _fields_ = [
        ("board", ctypes.c_int * MAX_BOARD_SIZE),
        ("n", ctypes.c_int),
        ("side", ctypes.c_int),
    ]


lib.kalah_set_board.argtypes = [
    ctypes.POINTER(CKalahState), ctypes.c_int,
    ctypes.POINTER(ctypes.c_int), ctypes.c_int
]
lib.kalah_set_board.restype = None

lib.kalah_copy.argtypes = [
    ctypes.POINTER(CKalahState), ctypes.POINTER(CKalahState)
]
lib.kalah_copy.restype = None

lib.kalah_is_terminal.argtypes = [ctypes.POINTER(CKalahState)]
lib.kalah_is_terminal.restype = ctypes.c_int

lib.kalah_terminal_score.argtypes = [ctypes.POINTER(CKalahState)]
lib.kalah_terminal_score.restype = ctypes.c_int

lib.kalah_make_move.argtypes = [
    ctypes.POINTER(CKalahState), ctypes.c_int, ctypes.c_int
]
lib.kalah_make_move.restype = ctypes.c_int

lib.kalah_legal_moves.argtypes = [
    ctypes.POINTER(CKalahState), ctypes.POINTER(ctypes.c_int)
]
lib.kalah_legal_moves.restype = ctypes.c_int


# ---------------------------------------------------------------------------
# State wrapper
# ---------------------------------------------------------------------------

class State:
    __slots__ = ['_cs']

    def __init__(self, n=None, board=None, side=0, _cs=None):
        if _cs is not None:
            self._cs = _cs
        else:
            self._cs = CKalahState()
            if board is not None:
                arr = (ctypes.c_int * MAX_BOARD_SIZE)()
                for i, v in enumerate(board):
                    arr[i] = v
                lib.kalah_set_board(ctypes.byref(self._cs), n, arr, side)

    def clone(self):
        cs = CKalahState()
        lib.kalah_copy(ctypes.byref(cs), ctypes.byref(self._cs))
        return State(_cs=cs)

    def key(self):
        n = self._cs.n
        total = 2 * (n + 1)
        return (tuple(self._cs.board[i] for i in range(total)), self._cs.side)

    @property
    def side(self):
        return self._cs.side

    @property
    def n(self):
        return self._cs.n

    def legal_moves(self):
        moves = (ctypes.c_int * 8)()
        count = lib.kalah_legal_moves(ctypes.byref(self._cs), moves)
        return [moves[i] for i in range(count)]

    def is_terminal(self):
        return bool(lib.kalah_is_terminal(ctypes.byref(self._cs)))

    def terminal_score(self):
        return lib.kalah_terminal_score(ctypes.byref(self._cs))

    def make_move(self, pit, captures=True):
        return bool(lib.kalah_make_move(
            ctypes.byref(self._cs), pit, 1 if captures else 0
        ))


# ---------------------------------------------------------------------------
# Minimax solver with memoization
# ---------------------------------------------------------------------------

def minimax(state, captures, tt):
    key = state.key()
    if key in tt:
        return tt[key]

    if state.is_terminal():
        v = state.terminal_score()
        tt[key] = (v, -1)
        return v, -1

    moves = state.legal_moves()
    best_move = moves[0]

    if state.side == 0:  # South maximises
        best = -9999
        for m in moves:
            c = state.clone()
            c.make_move(m, captures)
            v, _ = minimax(c, captures, tt)
            if v > best:
                best = v
                best_move = m
    else:  # North minimises
        best = 9999
        for m in moves:
            c = state.clone()
            c.make_move(m, captures)
            v, _ = minimax(c, captures, tt)
            if v < best:
                best = v
                best_move = m

    tt[key] = (best, best_move)
    return best, best_move


# ---------------------------------------------------------------------------
# Enumerate all distributions of stones into positions
# ---------------------------------------------------------------------------

def enumerate_distributions(total, num_pos):
    if num_pos == 1:
        yield [total]
        return
    for k in range(total + 1):
        for rest in enumerate_distributions(total - k, num_pos - 1):
            yield [k] + rest


# ---------------------------------------------------------------------------
# Build endgame database
# ---------------------------------------------------------------------------

def build_endgame_db(n, seeds, captures, conn):
    total_stones = 2 * n * seeds
    num_pos = 2 * (n + 1)
    tt = {}

    for dist in enumerate_distributions(total_stones, num_pos):
        for side in [0, 1]:
            state = State(n=n, board=dist, side=side)
            minimax(state, captures, tt)

    cursor = conn.cursor()
    captures_int = 1 if captures else 0
    for key, (value, best_move) in tt.items():
        board_tuple, side = key
        board_key = ",".join(str(x) for x in board_tuple)
        cursor.execute(
            "INSERT OR REPLACE INTO endgame_positions "
            "(board_key, n, side, total_stones, value, best_move, captures) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (board_key, n, side, total_stones, value, best_move, captures_int)
        )
    conn.commit()
    return tt


# ---------------------------------------------------------------------------
# Pie-rule analysis
# ---------------------------------------------------------------------------

def enum_first_turn(state, captures, seq, results):
    for m in state.legal_moves():
        child = state.clone()
        extra = child.make_move(m, captures)
        new_seq = seq + [m]
        if extra and not child.is_terminal() and child.legal_moves():
            enum_first_turn(child, captures, new_seq, results)
        else:
            results.append((child, new_seq))


def compute_pie_value(state, captures, tt):
    outcomes = []
    enum_first_turn(state, captures, [], outcomes)

    best_pie = -9999
    best_seq = None

    for child, seq in outcomes:
        if child.is_terminal():
            val = child.terminal_score()
        else:
            val, _ = minimax(child, captures, tt)

        if val > 0:
            south_gets = -val
        elif val < 0:
            south_gets = val
        else:
            south_gets = 0

        if south_gets > best_pie:
            best_pie = south_gets
            best_seq = seq

    return best_pie, best_seq


# ---------------------------------------------------------------------------
# Balance statistics
# ---------------------------------------------------------------------------

def compute_balance(tt):
    south_win = 0
    draw = 0
    north_win = 0
    total = 0

    for key, (value, _) in tt.items():
        _, side = key
        if side != 0:
            continue
        total += 1
        if value > 0:
            south_win += 1
        elif value == 0:
            draw += 1
        else:
            north_win += 1

    return {
        "south_win_frac": round(south_win / total, 6),
        "draw_frac": round(draw / total, 6),
        "north_win_frac": round(north_win / total, 6),
        "total_positions": total,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    with open("/app/positions.json") as f:
        positions = json.load(f)

    # Initialize SQLite
    db_path = "/app/endgame.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    with open("/app/schema.sql") as f:
        conn.executescript(f.read())

    # Build endgame databases and compute balance stats
    balance = {}
    db_tts = {}

    for seeds in [1, 2]:
        n = 3
        total_stones = 2 * n * seeds
        for captures in [True, False]:
            variant = "standard" if captures else "fairkalah"
            print(f"Building endgame DB: Kalah({n},{seeds}) {variant}...")
            tt = build_endgame_db(n, seeds, captures, conn)
            key = f"{n}_{seeds}_{variant}"
            balance[key] = compute_balance(tt)
            db_tts[(n, total_stones, captures)] = tt
            print(f"  {key}: {balance[key]}")

    conn.execute(
        "INSERT OR REPLACE INTO metadata VALUES ('balance', ?)",
        (json.dumps(balance),)
    )
    conn.commit()

    # Solve positions
    results_pos = {}

    for pos in positions:
        pid = pos["id"]
        n = pos["pits_per_side"]
        board = (list(pos["south_pits"]) + [pos["south_store"]] +
                 list(pos["north_pits"]) + [pos["north_store"]])
        total_stones = sum(board)
        side = 0 if pos["side_to_move"] == "south" else 1

        print(f"Solving {pid} ({pos['description']})...")

        # Standard rules
        db_key_std = (n, total_stones, True)
        if db_key_std in db_tts:
            state = State(n=n, board=board, side=side)
            std_val, std_move = db_tts[db_key_std][state.key()]
        else:
            std_tt = {}
            state = State(n=n, board=board, side=side)
            std_val, std_move = minimax(state, True, std_tt)
        print(f"  Standard: value={std_val}, best_move={std_move}")

        # FairKalah rules
        db_key_fair = (n, total_stones, False)
        if db_key_fair in db_tts:
            state = State(n=n, board=board, side=side)
            fair_val, fair_move = db_tts[db_key_fair][state.key()]
            fair_tt = db_tts[db_key_fair]
        else:
            fair_tt = {}
            state = State(n=n, board=board, side=side)
            fair_val, fair_move = minimax(state, False, fair_tt)
            db_tts[db_key_fair] = fair_tt
        print(f"  FairKalah: value={fair_val}, best_move={fair_move}")

        # Pie rule (FairKalah, South to move only)
        if pos["side_to_move"] == "south":
            state = State(n=n, board=board, side=side)
            pie_val, pie_seq = compute_pie_value(state, False, fair_tt)
            print(f"  Pie rule: value={pie_val}, first_moves={pie_seq}")
        else:
            pie_val = None
            pie_seq = None
            print("  Pie rule: N/A (not South's turn)")

        results_pos[pid] = {
            "standard_value": std_val,
            "standard_best_move": std_move,
            "fairkalah_value": fair_val,
            "fairkalah_best_move": fair_move,
            "pie_rule_value": pie_val,
            "pie_rule_first_moves": pie_seq,
        }

    # Write results
    results = {"positions": results_pos, "balance": balance}
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    conn.close()
    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
