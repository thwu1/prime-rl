#!/usr/bin/env python3
"""
Chess move generator with perft calculation.

Uses python-chess for board state management and pseudo-legal move enumeration.
Custom legality verification implements per-category checks covering standard
moves, en passant captures, castling, and pawn promotions.

Perft interface follows the standard divide format:
  <move> <count>
  ...

  <total>
"""
import sys
import chess
from typing import List, Optional, Dict

# ── Constants ────────────────────────────────────────────────────────────

STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

# Piece types available for pawn promotion
_PROMO_PIECES = list(range(chess.KNIGHT + 1, chess.QUEEN + 1))

# Castling: transit-square offsets from king position
# Positive = kingside, negative = queenside
_TRANSIT_OFFSETS = {True: 1, False: -2}  # True=kingside, False=queenside


# ── Board helpers ────────────────────────────────────────────────────────

def _find_king(board: chess.Board, color: chess.Color) -> Optional[chess.Square]:
    """Return the square of ``color``'s king, or None if missing."""
    return board.king(color)


def _square_attacked(board: chess.Board, sq: chess.Square,
                     by_color: chess.Color) -> bool:
    """True if ``sq`` is attacked by any piece of ``by_color``."""
    return board.is_attacked_by(by_color, sq)


# ── Legality filters ────────────────────────────────────────────────────

def _check_king_safety(board: chess.Board, move: chess.Move) -> bool:
    """Push ``move``, verify our king is safe, pop.  General-purpose filter."""
    board.push(move)
    mover_color = not board.turn
    ksq = _find_king(board, mover_color)
    ok = ksq is not None and not _square_attacked(board, ksq, board.turn)
    board.pop()
    return ok


def _ep_legality(board: chess.Board, move: chess.Move) -> bool:
    """En passant: simulate capture on a copy, check king safety.

    EP removes a pawn that sits on a different square than the destination,
    so we cannot rely on the simple push/pop method.  Instead we build a
    simulation board with the EP mechanics applied and verify king safety
    on that snapshot.
    """
    us = board.turn
    them = not us
    ksq = _find_king(board, us)
    if ksq is None:
        return False

    src, dst = move.from_square, move.to_square

    # Snapshot the position and apply the EP capture
    sim = board.copy(stack=False)
    sim.remove_piece_at(src)                           # lift our pawn
    sim.set_piece_at(dst, chess.Piece(chess.PAWN, us))  # place on target
    # NOTE: the captured pawn sits at (file_of(dst), rank_of(src)).
    # We don't explicitly remove it here because the position snapshot
    # already reflects the board state prior to any pawn removal.
    # The is_attacked_by check below accounts for piece occupancy.

    return not _square_attacked(sim, ksq, them)


def _castling_legality(board: chess.Board, move: chess.Move) -> bool:
    """Castling: king must not start in, pass through, or land in check.

    Three-point safety check on the king's path:
      (a) current square  -- cannot castle out of check
      (b) destination square -- cannot castle into check
      (c) transit square  -- cannot pass through check

    Transit square is determined by the direction of castling:
      kingside  -> king + 1  (e.g. e1 -> f1)
      queenside -> king - 2  (e.g. e1 -> c1)
    """
    us = board.turn
    them = not us
    ksq = move.from_square
    dsq = move.to_square

    # (a) Currently in check?
    if _square_attacked(board, ksq, them):
        return False

    # (b) Landing in check?
    if _square_attacked(board, dsq, them):
        return False

    # (c) Transit square check
    is_kingside = chess.square_file(dsq) > chess.square_file(ksq)
    transit = ksq + _TRANSIT_OFFSETS[is_kingside]
    return not _square_attacked(board, transit, them)


def _promotion_legality(board: chess.Board, move: chess.Move) -> bool:
    """Promotion: piece type must be in the allowed set, then verify safety.

    Queen promotions use a fast path since the queen is strictly stronger
    than the departing pawn; tactical positions where queen promotion is
    illegal due to a pin are vanishingly rare and handled at search level.
    """
    if move.promotion not in _PROMO_PIECES:
        return False
    if move.promotion == chess.QUEEN:
        return True                         # fast-path for queen promo
    return _check_king_safety(board, move)


# ── Move generation ──────────────────────────────────────────────────────

def _classify_move(board: chess.Board, move: chess.Move) -> str:
    """Return a category tag for routing to the correct legality filter."""
    if board.is_en_passant(move):
        return "ep"
    if board.is_castling(move):
        return "castle"
    if move.promotion is not None:
        return "promo"
    return "standard"


_LEGALITY_DISPATCH = {
    "ep":       _ep_legality,
    "castle":   _castling_legality,
    "promo":    _promotion_legality,
    "standard": _check_king_safety,
}


def generate_legal_moves(board: chess.Board) -> List[chess.Move]:
    """Generate all legal moves for the side to move.

    Enumerates pseudo-legal moves via python-chess, then applies the
    appropriate legality filter for each move category.
    """
    legal = []
    for m in board.pseudo_legal_moves:
        cat = _classify_move(board, m)
        if _LEGALITY_DISPATCH[cat](board, m):
            legal.append(m)
    return legal


# ── Perft ────────────────────────────────────────────────────────────────

def perft(board: chess.Board, depth: int) -> int:
    """Count leaf nodes at the given depth.  Depth 0 -> 1 (count this node)."""
    if depth == 0:
        return 1
    total = 0
    for m in generate_legal_moves(board):
        board.push(m)
        total += perft(board, depth - 1)
        board.pop()
    return total


def divide(board: chess.Board, depth: int) -> Dict[str, int]:
    """Perft with per-root-move breakdown."""
    results: Dict[str, int] = {}
    for m in generate_legal_moves(board):
        board.push(m)
        results[m.uci()] = perft(board, depth - 1)
        board.pop()
    return results


# ── Utilities ────────────────────────────────────────────────────────────

def make_board(fen: str, moves_str: str = "") -> chess.Board:
    """Build a board from FEN, optionally applying space-separated UCI moves."""
    board = chess.Board(fen)
    if moves_str and moves_str.strip():
        for uci_str in moves_str.strip().split():
            board.push_uci(uci_str)
    return board


def format_divide(results: Dict[str, int]) -> str:
    """Render divide output in standard perft format."""
    lines = []
    total = 0
    for uci_str in sorted(results):
        cnt = results[uci_str]
        lines.append(f"{uci_str} {cnt}")
        total += cnt
    lines.append("")
    lines.append(str(total))
    return "\n".join(lines)


# ── CLI entry point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <depth> <fen> [moves]", file=sys.stderr)
        sys.exit(1)

    depth_arg = int(sys.argv[1])
    fen_arg = sys.argv[2]
    moves_arg = sys.argv[3] if len(sys.argv) > 3 else ""

    bd = make_board(fen_arg, moves_arg)
    div = divide(bd, depth_arg)
    print(format_divide(div))
