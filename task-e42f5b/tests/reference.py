"""Reference implementation of the relay-sowing Mancala variant.

Relay (lap) sowing rule: after distributing seeds, if the last seed lands in a
non-store pit that already contained seeds (count > 1 after drop), pick up ALL
seeds from that pit and continue sowing.  Repeat until the last seed lands in
(a) the player's own store, or (b) a pit that was empty before (now == 1).

No captures.  Extra turn if last seed lands in own store.
Game ends when either side's pits are all empty; remaining pit seeds go to
their respective stores.
"""

import sys

sys.setrecursionlimit(500000)


def get_moves(board, side, h):
    """Return list of legal pit indices for the given side."""
    if side == 0:
        return [i for i in range(h) if board[i] > 0]
    else:
        return [i for i in range(h + 1, 2 * h + 1) if board[i] > 0]


def make_move(board, side, pit, h):
    """Execute a relay-sowing move.
    Returns (new_board_tuple, new_side) where new_side == -1 means game over.
    """
    size = 2 * h + 2
    b = list(board)
    my_store = h if side == 0 else size - 1
    opp_store = size - 1 if side == 0 else h

    seeds = b[pit]
    b[pit] = 0
    pos = pit

    while True:
        for _ in range(seeds):
            pos = (pos + 1) % size
            if pos == opp_store:
                pos = (pos + 1) % size
            b[pos] += 1
        if pos == my_store:
            break
        if b[pos] <= 1:
            break
        seeds = b[pos]
        b[pos] = 0

    south_empty = all(b[i] == 0 for i in range(h))
    north_empty = all(b[i] == 0 for i in range(h + 1, 2 * h + 1))

    if south_empty or north_empty:
        for i in range(h):
            b[h] += b[i]; b[i] = 0
        for i in range(h + 1, 2 * h + 1):
            b[size - 1] += b[i]; b[i] = 0
        return tuple(b), -1

    next_side = side if pos == my_store else 1 - side
    return tuple(b), next_side


def solve(board, side, h, memo=None):
    """Game-theoretic value from South's perspective (memoised minimax)."""
    if memo is None:
        memo = {}

    size = 2 * h + 2

    south_empty = all(board[i] == 0 for i in range(h))
    north_empty = all(board[i] == 0 for i in range(h + 1, 2 * h + 1))
    if south_empty or north_empty:
        s = sum(board[i] for i in range(h + 1))
        n = sum(board[i] for i in range(h + 1, size))
        return s - n

    key = (tuple(board) if not isinstance(board, tuple) else board, side)
    if key in memo:
        return memo[key]

    moves = get_moves(board, side, h)

    if side == 0:
        best = -9999
        for m in moves:
            nb, ns = make_move(board, side, m, h)
            if ns == -1:
                v = nb[h] - nb[size - 1]
            else:
                v = solve(nb, ns, h, memo)
            if v > best:
                best = v
    else:
        best = 9999
        for m in moves:
            nb, ns = make_move(board, side, m, h)
            if ns == -1:
                v = nb[h] - nb[size - 1]
            else:
                v = solve(nb, ns, h, memo)
            if v < best:
                best = v

    memo[key] = best
    return best


def solve_initial(h, s):
    """Solve from the standard initial position (h pits, s seeds each)."""
    board = tuple([s] * h + [0] + [s] * h + [0])
    return solve(board, 0, h)


# ---------------------------------------------------------------------------
# Extended analysis functions for endgame DB and PV verification
# ---------------------------------------------------------------------------

_complete_cache = {}


def _solve_complete(h, s):
    """Full solve with best-move tracking.
    Returns (value, memo, best_moves) where:
      memo[(board,side)] = game-theoretic value
      best_moves[(board,side)] = optimal pit index
    """
    if (h, s) in _complete_cache:
        return _complete_cache[(h, s)]

    initial_board = tuple([s] * h + [0] + [s] * h + [0])
    memo = {}
    best_moves = {}

    def _solve(board, side):
        size = 2 * h + 2
        se = all(board[i] == 0 for i in range(h))
        ne = all(board[i] == 0 for i in range(h + 1, 2 * h + 1))
        if se or ne:
            return (sum(board[i] for i in range(h + 1))
                    - sum(board[i] for i in range(h + 1, size)))
        key = (board, side)
        if key in memo:
            return memo[key]
        mvs = get_moves(board, side, h)
        bm = None
        if side == 0:
            best = -9999
            for m in mvs:
                nb, ns = make_move(board, side, m, h)
                v = (nb[h] - nb[size - 1]) if ns == -1 else _solve(nb, ns)
                if v > best:
                    best = v; bm = m
        else:
            best = 9999
            for m in mvs:
                nb, ns = make_move(board, side, m, h)
                v = (nb[h] - nb[size - 1]) if ns == -1 else _solve(nb, ns)
                if v < best:
                    best = v; bm = m
        memo[key] = best
        best_moves[key] = bm
        return best

    value = _solve(initial_board, 0)
    result = (value, memo, best_moves)
    _complete_cache[(h, s)] = result
    return result


def count_reachable(h, s):
    """Count non-terminal (board, side) pairs reachable from (h,s) initial."""
    _, memo, _ = _solve_complete(h, s)
    return len(memo)


def get_principal_variation(h, s):
    """Return the principal variation as list of {side, pit, board_after}."""
    _, _, best_moves = _solve_complete(h, s)
    initial_board = tuple([s] * h + [0] + [s] * h + [0])
    pv = []
    board = initial_board
    side = 0
    for _ in range(1000):
        key = (board, side)
        if key not in best_moves:
            break
        pit = best_moves[key]
        nb, ns = make_move(board, side, pit, h)
        pv.append({"side": side, "pit": pit, "board_after": list(nb)})
        if ns == -1:
            break
        board, side = nb, ns
    return pv
