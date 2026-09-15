
"""
Python reference implementation of the Crown board game.
Used for computing ground-truth perft values to verify the RBG implementation.
"""

EMPTY = 0
WS, WN, WG, WC, WK = 1, 2, 3, 4, 5   # White: Soldier, Knight, Guard, Chariot, King
BS, BN, BG, BC, BK = 6, 7, 8, 9, 10   # Black: Soldier, Knight, Guard, Chariot, King

WHITE_PIECES = frozenset({WS, WN, WG, WC, WK})
BLACK_PIECES = frozenset({BS, BN, BG, BC, BK})

ROWS, COLS = 6, 6

INITIAL_BOARD = (
    BC, BN, BG, BK, BN, BC,
    BS, BS, BS, BS, BS, BS,
    EMPTY, EMPTY, EMPTY, EMPTY, EMPTY, EMPTY,
    EMPTY, EMPTY, EMPTY, EMPTY, EMPTY, EMPTY,
    WS, WS, WS, WS, WS, WS,
    WC, WN, WG, WK, WN, WC,
)

WHITE = 0
BLACK = 1


def idx(r, c):
    return r * COLS + c


def in_bounds(r, c):
    return 0 <= r < ROWS and 0 <= c < COLS


def make_move(board, r1, c1, r2, c2, new_piece):
    b = list(board)
    b[idx(r1, c1)] = EMPTY
    b[idx(r2, c2)] = new_piece
    return tuple(b)


def own_pieces(player):
    return WHITE_PIECES if player == WHITE else BLACK_PIECES


def opp_pieces(player):
    return BLACK_PIECES if player == WHITE else WHITE_PIECES


def opp_king(player):
    return BK if player == WHITE else WK


def get_all_moves(board, player):
    """Returns list of new board states after all legal moves for `player`."""
    moves = []
    my_pcs = own_pieces(player)
    op_pcs = opp_pieces(player)
    forward = -1 if player == WHITE else 1

    for r in range(ROWS):
        for c in range(COLS):
            piece = board[idx(r, c)]
            if piece not in my_pcs:
                continue

            if piece == WS or piece == BS:
                _gen_soldier_moves(board, r, c, piece, forward, player, my_pcs, op_pcs, moves)
            elif piece == WN or piece == BN:
                _gen_knight_moves(board, r, c, piece, my_pcs, moves)
            elif piece == WG or piece == BG:
                _gen_slide_moves(board, r, c, piece, my_pcs, op_pcs, moves,
                                 [(-1, -1), (-1, 1), (1, -1), (1, 1)])
            elif piece == WC or piece == BC:
                _gen_slide_moves(board, r, c, piece, my_pcs, op_pcs, moves,
                                 [(-1, 0), (1, 0), (0, -1), (0, 1)])
            elif piece == WK or piece == BK:
                _gen_king_moves(board, r, c, piece, my_pcs, moves)

    return moves


def _gen_soldier_moves(board, r, c, piece, forward, player, my_pcs, op_pcs, moves):
    promote_row = 0 if player == WHITE else ROWS - 1
    promote_piece = WG if player == WHITE else BG

    # Forward to empty
    nr, nc = r + forward, c
    if in_bounds(nr, nc) and board[idx(nr, nc)] == EMPTY:
        placed = promote_piece if nr == promote_row else piece
        moves.append(make_move(board, r, c, nr, nc, placed))

    # Diagonal capture
    for dc in [-1, 1]:
        nr, nc = r + forward, c + dc
        if in_bounds(nr, nc) and board[idx(nr, nc)] in op_pcs:
            placed = promote_piece if nr == promote_row else piece
            moves.append(make_move(board, r, c, nr, nc, placed))


def _gen_knight_moves(board, r, c, piece, my_pcs, moves):
    for dr, dc in [(-2, -1), (-2, 1), (2, -1), (2, 1),
                   (-1, -2), (-1, 2), (1, -2), (1, 2)]:
        nr, nc = r + dr, c + dc
        if in_bounds(nr, nc) and board[idx(nr, nc)] not in my_pcs:
            moves.append(make_move(board, r, c, nr, nc, piece))


def _gen_slide_moves(board, r, c, piece, my_pcs, op_pcs, moves, directions):
    for dr, dc in directions:
        nr, nc = r + dr, c + dc
        while in_bounds(nr, nc):
            target = board[idx(nr, nc)]
            if target == EMPTY:
                moves.append(make_move(board, r, c, nr, nc, piece))
            elif target in op_pcs:
                moves.append(make_move(board, r, c, nr, nc, piece))
                break
            else:  # own piece
                break
            nr += dr
            nc += dc


def _gen_king_moves(board, r, c, piece, my_pcs, moves):
    for dr in [-1, 0, 1]:
        for dc in [-1, 0, 1]:
            if dr == 0 and dc == 0:
                continue
            nr, nc = r + dr, c + dc
            if in_bounds(nr, nc) and board[idx(nr, nc)] not in my_pcs:
                moves.append(make_move(board, r, c, nr, nc, piece))


def perft(board, player, depth):
    """Count leaf nodes at exactly `depth` player moves deep.

    Matches RBG perft semantics:
    - depth 0: always 1 (leaf)
    - King capture terminates the game; counts as leaf only at depth 0
    - Stalemate (no moves) at depth > 0: returns 0
    """
    if depth == 0:
        return 1

    all_moves = get_all_moves(board, player)
    if not all_moves:
        return 0  # stalemate at depth > 0

    count = 0
    opponent = 1 - player
    ok = opp_king(player)

    for new_board in all_moves:
        if ok not in new_board:
            # King captured — game terminal
            if depth == 1:
                count += 1  # terminal at depth 0 counts as leaf
            # depth > 1: terminal before reaching target depth, not counted
        else:
            count += perft(new_board, opponent, depth - 1)

    return count


def compute_reference_perft(max_depth=4):
    """Compute reference perft values for depths 1..max_depth."""
    results = {}
    for d in range(1, max_depth + 1):
        results[d] = perft(INITIAL_BOARD, WHITE, d)
    return results


if __name__ == "__main__":
    for d in range(1, 5):
        val = perft(INITIAL_BOARD, WHITE, d)
        print(f"perft({d}) = {val}")
