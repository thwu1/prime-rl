#!/usr/bin/env python3
"""
KRK (King+Rook vs King) endgame tablebase generator.

"""

import json
from collections import deque

# ── Constants ──────────────────────────────────────────
UNK = 255
DRW = 254
WHITE = 0
BLACK = 1
TABLE_SIZE = 64 * 64 * 64 * 2

# ── Square utilities ──────────────────────────────────
def rank_of(sq):
    return sq >> 3

def file_of(sq):
    return sq & 7

def make_sq(r, f):
    return (r << 3) | f

def king_distance(sq1, sq2):
    """Distance between two squares in king moves."""
    dr = abs(rank_of(sq1) - rank_of(sq2))
    df = abs(file_of(sq1) - file_of(sq2))
    return dr + df

def _compute_king_moves():
    result = [[] for _ in range(64)]
    for sq in range(64):
        r, f = rank_of(sq), file_of(sq)
        for dr in (-1, 0, 1):
            for df in (-1, 0, 1):
                if dr == 0 and df == 0:
                    continue
                nr, nf = r + dr, f + df
                if 0 <= nr < 8 and 0 <= nf < 8:
                    result[sq].append(make_sq(nr, nf))
    return result

KING_MOVES = _compute_king_moves()

# ── Rook attack detection ─────────────────────────────
def rook_attacks(rook_sq, target_sq, blocker_sq):
    """Does a rook on rook_sq attack target_sq, with blocker_sq as a potential blocker?"""
    if rook_sq == target_sq:
        return False
    rr, rf = rank_of(rook_sq), file_of(rook_sq)
    tr, tf = rank_of(target_sq), file_of(target_sq)
    br, bf = rank_of(blocker_sq), file_of(blocker_sq)

    if rr == tr:  # Same rank
        lo, hi = (rf, tf) if rf < tf else (tf, rf)
        if br == rr and lo < bf < hi:
            return False
        return True
    elif rf == tf:  # Same file
        lo, hi = (rr, tr) if rr < tr else (tr, rr)
        if bf == rf and lo < bf < hi:
            return False
        return True
    return False

# ── Indexing ──────────────────────────────────────────
def to_index(wk, wr, bk, stm):
    return ((wk * 64 + wr) * 64 + bk) * 2 + stm

def from_index(idx):
    stm = idx & 1
    idx >>= 1
    bk = idx & 63
    idx >>= 6
    wr = idx & 63
    wk = idx >> 6
    return wk, wr, bk, stm

# ── FEN parsing ───────────────────────────────────────
def parse_fen(fen):
    """Parse a KRK FEN string. Returns (wk, wr, bk, stm)."""
    parts = fen.split()
    board_str = parts[0]
    stm_char = parts[1] if len(parts) > 1 else 'w'
    stm = WHITE if stm_char == 'w' else BLACK

    wk = wr = bk = -1
    rank = 7
    file = 0
    for ch in board_str:
        if ch == '/':
            rank -= 1
            file = 0
        elif ch.isdigit():
            file += int(ch)
        else:
            sq = make_sq(rank, file)
            if ch == 'K':
                wk = sq
            elif ch == 'R':
                wr = sq
            elif ch == 'k':
                bk = sq
            file += 1

    if wk == -1 or wr == -1 or bk == -1:
        raise ValueError(f"Not a valid KRK FEN: {fen}")
    return wk, wr, bk, stm

# ── Module-level state ────────────────────────────────
_dtm_table = None
_legal_table = None
_stats = None

# ── Main algorithm ────────────────────────────────────
def generate():
    """Build the full KRK tablebase. Returns stats dict."""
    global _dtm_table, _legal_table, _stats
    if _dtm_table is not None:
        return _stats

    dtm = bytearray(bytes([UNK]) * TABLE_SIZE)
    legal = bytearray(TABLE_SIZE)
    move_count = bytearray(TABLE_SIZE)
    max_succ = bytearray(TABLE_SIZE)

    queue = deque()
    total_legal = 0
    total_draws = 0
    n_checkmates = 0
    n_stalemates = 0

    # ── Phase 1: enumerate legal positions ────────────
    for wk in range(64):
        for bk in range(64):
            if bk == wk or king_distance(wk, bk) <= 1:
                continue
            for wr in range(64):
                if wr == wk or wr == bk:
                    continue

                # --- WTM ---
                idx_w = to_index(wk, wr, bk, WHITE)
                if not rook_attacks(wr, bk, wk):
                    legal[idx_w] = 1
                    total_legal += 1

                # --- BTM ---
                idx_b = to_index(wk, wr, bk, BLACK)
                legal[idx_b] = 1
                total_legal += 1

                # Count BK legal moves within KRK
                n_moves = 0

                for t in KING_MOVES[bk]:
                    if king_distance(t, wk) <= 1:
                        continue
                    if t == wr:
                        continue
                    if rook_attacks(wr, t, wk):
                        continue
                    n_moves += 1

                if n_moves == 0:
                    in_check = rook_attacks(wr, bk, wk)
                    if in_check:
                        dtm[idx_b] = 0
                        n_checkmates += 1
                        queue.append(idx_b)
                    else:
                        dtm[idx_b] = DRW
                        total_draws += 1
                        n_stalemates += 1
                else:
                    move_count[idx_b] = n_moves

    # ── Phase 2: retrograde BFS ───────────────────────
    while queue:
        idx = queue.popleft()
        d = dtm[idx]
        wk, wr, bk, stm = from_index(idx)

        if stm == BLACK:
            # BTM resolved -> find WTM predecessors

            # Un-white-king-move
            for prev_wk in KING_MOVES[wk]:
                if prev_wk == wr or prev_wk == bk:
                    continue
                if king_distance(prev_wk, bk) <= 1:
                    continue
                if rook_attacks(wr, bk, prev_wk):
                    continue
                pidx = to_index(prev_wk, wr, bk, WHITE)
                if legal[pidx] and dtm[pidx] == UNK:
                    dtm[pidx] = d + 1
                    queue.append(pidx)

            # Un-white-rook-move
            rr, rf = rank_of(wr), file_of(wr)

            # Along same rank
            for f in range(8):
                prev_wr = make_sq(rr, f)
                if prev_wr == wr or prev_wr == wk or prev_wr == bk:
                    continue
                lo, hi = (f, rf) if f < rf else (rf, f)
                blocked = False
                for bf in range(lo + 1, hi):
                    sq = make_sq(rr, bf)
                    if sq == wk or sq == bk:
                        blocked = True
                        break
                if blocked:
                    continue
                if rook_attacks(prev_wr, bk, wk):
                    continue
                pidx = to_index(wk, prev_wr, bk, WHITE)
                if legal[pidx] and dtm[pidx] == UNK:
                    dtm[pidx] = d + 1
                    queue.append(pidx)

            # Along same file
            for r in range(8):
                prev_wr = make_sq(r, rf)
                if prev_wr == wr or prev_wr == wk or prev_wr == bk:
                    continue
                lo, hi = (r, rr) if r < rr else (rr, r)
                blocked = False
                for br in range(lo + 1, hi):
                    sq = make_sq(br, rf)
                    if sq == wk or sq == bk:
                        blocked = True
                        break
                if blocked:
                    continue
                if rook_attacks(prev_wr, bk, wk):
                    continue
                pidx = to_index(wk, prev_wr, bk, WHITE)
                if legal[pidx] and dtm[pidx] == UNK:
                    dtm[pidx] = d + 1
                    queue.append(pidx)

        else:
            # WTM resolved -> find BTM predecessors

            for prev_bk in KING_MOVES[bk]:
                if prev_bk == wk or prev_bk == wr:
                    continue
                if king_distance(prev_bk, wk) <= 1:
                    continue
                pidx = to_index(wk, wr, prev_bk, BLACK)
                if legal[pidx] and dtm[pidx] == UNK:
                    move_count[pidx] -= 1
                    if d > max_succ[pidx]:
                        max_succ[pidx] = d
                    if move_count[pidx] == 0:
                        dtm[pidx] = max_succ[pidx] + 1
                        queue.append(pidx)

    # ── Phase 3: remaining unknowns ──────────────────
    remaining = 0
    for i in range(TABLE_SIZE):
        if legal[i] and dtm[i] == UNK:
            remaining += 1
            dtm[i] = DRW
            total_draws += 1

    # ── Compute statistics ────────────────────────────
    total_wins = total_legal - total_draws
    max_d = 0
    for i in range(TABLE_SIZE):
        if legal[i] and dtm[i] < DRW and dtm[i] > max_d:
            max_d = dtm[i]

    stats = {
        "total_positions": total_legal,
        "white_wins": total_wins,
        "draws": total_draws,
        "max_dtm_plies": max_d,
        "checkmates": n_checkmates,
        "stalemates": n_stalemates,
        "remaining_unknown": remaining,
    }

    _dtm_table = dtm
    _legal_table = legal
    _stats = stats
    return stats


def lookup_fen(fen):
    """Look up DTM for a KRK FEN position.
    Returns int >= 0 for wins (DTM in plies), -1 for draws.
    Raises ValueError for illegal or non-KRK positions."""
    global _dtm_table, _legal_table
    if _dtm_table is None:
        generate()

    wk, wr, bk, stm = parse_fen(fen)

    if wk == wr or wk == bk or wr == bk:
        raise ValueError("Pieces overlap")
    if king_distance(wk, bk) <= 1:
        raise ValueError("Kings adjacent")

    idx = to_index(wk, wr, bk, stm)
    if not _legal_table[idx]:
        raise ValueError(f"Illegal position: {fen}")

    val = _dtm_table[idx]
    if val == DRW:
        return -1
    return val


if __name__ == "__main__":
    print("Generating KRK endgame tablebase...", flush=True)
    stats = generate()

    out_path = "/app/krk_results.json"
    with open(out_path, "w") as f:
        json.dump(stats, f, indent=2)

    print(f"Results written to {out_path}")
    for k, v in stats.items():
        print(f"  {k}: {v}")
