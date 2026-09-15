#!/usr/bin/env python3
"""
Patch four bugs in /app/chess_engine.py and verify the fixes.

Bug 1: En passant simulation omits captured pawn removal -- horizontal pins
        through the captured pawn's square go undetected.
Bug 2: Queenside castling transit offset is -2 (c-file) instead of -1 (d-file).
Bug 3: Promotion type range starts at KNIGHT+1, excluding knight underpromotion.
Bug 4: Queen promotions skip the king-safety check (disguised as a fast-path
        optimization), allowing pinned pawns to promote to queen illegally.

"""
import sys

ENGINE = "/app/chess_engine.py"

with open(ENGINE) as f:
    content = f.read()

original = content

# ── Fix 1: EP must remove captured pawn ──────────────────────────────────
# The captured pawn sits at (file_of(dst), rank_of(src)).  Without removing
# it, the simulation board still has that pawn blocking rook/queen attacks
# along the rank, so horizontal pins through the captured pawn go undetected.
old_ep = (
    "    sim.set_piece_at(dst, chess.Piece(chess.PAWN, us))  # place on target\n"
    "    # NOTE: the captured pawn sits at (file_of(dst), rank_of(src)).\n"
    "    # We don't explicitly remove it here because the position snapshot\n"
    "    # already reflects the board state prior to any pawn removal.\n"
    "    # The is_attacked_by check below accounts for piece occupancy."
)
new_ep = (
    "    sim.set_piece_at(dst, chess.Piece(chess.PAWN, us))  # place on target\n"
    "    # Remove the captured pawn (sits at dst_file, src_rank)\n"
    "    captured_sq = chess.square(chess.square_file(dst), chess.square_rank(src))\n"
    "    sim.remove_piece_at(captured_sq)"
)
assert old_ep in content, "EP bug pattern not found in engine"
content = content.replace(old_ep, new_ep)

# ── Fix 2: Queenside castling transit offset -2 -> -1 ───────────────────
old_transit = "False: -2}"
new_transit = "False: -1}"
assert old_transit in content, "Castling transit bug pattern not found"
content = content.replace(old_transit, new_transit)

# ── Fix 3: Promotion range must include KNIGHT ──────────────────────────
old_promo_range = "chess.KNIGHT + 1, chess.QUEEN + 1"
new_promo_range = "chess.KNIGHT, chess.QUEEN + 1"
assert old_promo_range in content, "Promotion range bug pattern not found"
content = content.replace(old_promo_range, new_promo_range)

# ── Fix 4: Remove queen promotion fast-path (it skips safety check) ─────
old_queen_fast = (
    "    if move.promotion == chess.QUEEN:\n"
    "        return True                         # fast-path for queen promo\n"
)
assert old_queen_fast in content, "Queen promo fast-path bug pattern not found"
content = content.replace(old_queen_fast, "")

assert content != original, "No changes were applied"

with open(ENGINE, "w") as f:
    f.write(content)

print("All four bugs patched successfully.")

# ── Smoke tests ─────────────────────────────────────────────────────────
import importlib

sys.path.insert(0, "/app")
import chess
import chess_engine
importlib.reload(chess_engine)
from chess_engine import generate_legal_moves, perft

# Bug 1: EP horizontal pin must be blocked
board = chess.Board("8/8/8/KPp4r/8/8/8/4k3 w - c6 0 1")
moves = {m.uci() for m in generate_legal_moves(board)}
assert "b5c6" not in moves, "EP horizontal pin bug still present"

# Bug 2: Queenside castling through attacked transit
board = chess.Board("r3k3/8/8/8/8/8/8/3QK3 b q - 0 1")
moves = {m.uci() for m in generate_legal_moves(board)}
assert "e8c8" not in moves, "Castling transit bug still present"

# Bug 3: Knight promotion
board = chess.Board("8/P7/8/8/8/8/8/4K2k w - - 0 1")
moves = {m.uci() for m in generate_legal_moves(board)}
assert "a7a8n" in moves, "Knight promotion still missing"

# Bug 4: Queen promotion safety
board = chess.Board("8/K1P4r/8/8/8/8/8/7k w - - 0 1")
moves = {m.uci() for m in generate_legal_moves(board)}
assert "c7c8q" not in moves, "Queen promotion safety bug still present"

# Perft spot checks
board = chess.Board("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1")
r = perft(board, 3)
assert r == 2812, f"Position 3 perft(3) = {r}, expected 2812"

board = chess.Board(
    "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1"
)
r = perft(board, 3)
assert r == 9467, f"Position 4 perft(3) = {r}, expected 9467"

print("All smoke tests passed.")
