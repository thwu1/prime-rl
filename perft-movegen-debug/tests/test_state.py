"""
Tests for chess engine move generator correctness via perft comparison.

Validates perft values against known-correct results for standard positions,
checks specific edge cases for each move legality category, and verifies
the perft comparison tool is functional.

"""
import sys
import os
import subprocess
import re

sys.path.insert(0, "/app")

import chess
from chess_engine import generate_legal_moves, perft, make_board


# ── Standard perft positions ────────────────────────────────────────────

class TestPerftStandardPositions:
    """Verify perft node counts against known-correct values."""

    def test_initial_position_depth3(self):
        """Starting position perft(3) = 8902."""
        board = chess.Board(
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        )
        result = perft(board, 3)
        assert result == 8902, f"perft(3) = {result}, expected 8902"

    def test_kiwipete_depth3(self):
        """Position 2 (Kiwipete) perft(3) = 97862. Rich in tactical motifs."""
        board = chess.Board(
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq -"
        )
        result = perft(board, 3)
        assert result == 97862, f"Kiwipete perft(3) = {result}, expected 97862"

    def test_position3_depth4(self):
        """Position 3 perft(4) = 43238. Exercises en passant edge cases."""
        board = chess.Board("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1")
        result = perft(board, 4)
        assert result == 43238, f"Pos3 perft(4) = {result}, expected 43238"

    def test_position4_depth3(self):
        """Position 4 perft(3) = 9467. Exercises castling and promotion."""
        board = chess.Board(
            "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1"
        )
        result = perft(board, 3)
        assert result == 9467, f"Pos4 perft(3) = {result}, expected 9467"

    def test_position5_depth3(self):
        """Position 5 perft(3) = 62379. Exercises d-file promotion."""
        board = chess.Board(
            "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8"
        )
        result = perft(board, 3)
        assert result == 62379, f"Pos5 perft(3) = {result}, expected 62379"


# ── En passant horizontal pin ───────────────────────────────────────────

class TestEPHorizontalPin:
    """En passant must be rejected when it exposes king to horizontal attack."""

    def test_ep_pin_rank5(self):
        """King a5, own pawn b5, opponent pawn c5 (just double-pushed), rook h5.
        EP bxc6 removes both b5 and c5 from rank 5, exposing king to rook."""
        board = chess.Board("8/8/8/KPp4r/8/8/8/4k3 w - c6 0 1")
        moves = {m.uci() for m in generate_legal_moves(board)}
        assert "b5c6" not in moves, (
            "EP b5c6 illegal: both pawns leave rank 5, exposing king a5 to rook h5"
        )

    def test_ep_no_pin(self):
        """Same pawns but king off the rank -- EP is legal."""
        board = chess.Board("8/8/8/1Pp5/8/8/8/K3k3 w - c6 0 1")
        moves = {m.uci() for m in generate_legal_moves(board)}
        assert "b5c6" in moves, "EP b5c6 should be legal when no pin exists"

    def test_ep_position3_subline(self):
        """After Rb1 c5 from Position 3, EP b5xc6 is horizontally pinned."""
        board = make_board(
            "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
            "b4b1 c7c5"
        )
        moves = {m.uci() for m in generate_legal_moves(board)}
        assert "b5c6" not in moves, (
            "After Rb1 c5, EP b5c6 is illegal due to horizontal pin"
        )


# ── Castling transit square ─────────────────────────────────────────────

class TestCastlingTransit:
    """Queenside castling must check the d-file transit square, not c-file."""

    def test_queenside_through_attacked_d8(self):
        """Black king e8, rook a8. White queen on d1 attacks d8.
        O-O-O crosses d8 which is attacked -- must be rejected."""
        board = chess.Board("r3k3/8/8/8/8/8/8/3QK3 b q - 0 1")
        moves = {m.uci() for m in generate_legal_moves(board)}
        assert "e8c8" not in moves, (
            "O-O-O e8c8 illegal: transit square d8 attacked by queen on d1"
        )

    def test_queenside_safe_path(self):
        """With no pieces attacking the path, O-O-O should be legal."""
        board = chess.Board("r3k3/8/8/8/8/8/8/4K3 b q - 0 1")
        moves = {m.uci() for m in generate_legal_moves(board)}
        assert "e8c8" in moves, "O-O-O should be legal when path is clear"

    def test_kingside_unaffected(self):
        """Kingside castling transit (f-file) should still work correctly."""
        board = chess.Board("r3k2r/8/8/8/8/5B2/8/4K3 b k - 0 1")
        moves = {m.uci() for m in generate_legal_moves(board)}
        assert "e8g8" in moves, "O-O should be legal when f8 is safe"


# ── Knight (under)promotion ─────────────────────────────────────────────

class TestKnightPromotion:
    """All four promotion types must be generated, including knight."""

    def test_all_four_promotion_types_push(self):
        """Pawn push to 8th rank must offer Q, R, B, and N promotions."""
        board = chess.Board("8/P7/8/8/8/8/8/4K2k w - - 0 1")
        moves = {m.uci() for m in generate_legal_moves(board)}
        for suffix in ["q", "r", "b", "n"]:
            assert f"a7a8{suffix}" in moves, (
                f"Promotion a7a8{suffix} must be generated"
            )

    def test_knight_capture_promotion(self):
        """Knight promotion via capture must also be generated."""
        board = chess.Board("1n6/P7/8/8/8/8/8/4K2k w - - 0 1")
        moves = {m.uci() for m in generate_legal_moves(board)}
        for suffix in ["q", "r", "b", "n"]:
            assert f"a7b8{suffix}" in moves, (
                f"Capture-promotion a7b8{suffix} must be generated"
            )


# ── Queen promotion safety ──────────────────────────────────────────────

class TestQueenPromotionSafety:
    """Queen promotions must undergo king-safety checks like all other moves."""

    def test_pinned_pawn_queen_promo_illegal(self):
        """Pawn c7 pinned to king a7 by rook h7 along rank 7.
        Any promotion from c7 exposes king to rook -- all must be rejected."""
        board = chess.Board("8/K1P4r/8/8/8/8/8/7k w - - 0 1")
        moves = {m.uci() for m in generate_legal_moves(board)}
        assert "c7c8q" not in moves, (
            "c7c8q illegal: pawn c7 pinned along rank 7 to king a7 by rook h7"
        )

    def test_unpinned_queen_promo_legal(self):
        """When the promoting pawn is not pinned, queen promotion is legal."""
        board = chess.Board("8/2P5/8/8/8/8/8/K6k w - - 0 1")
        moves = {m.uci() for m in generate_legal_moves(board)}
        assert "c7c8q" in moves, "Unpinned queen promotion must be legal"

    def test_pinned_pawn_perft1(self):
        """Perft(1) for pinned-pawn position: only 5 king moves are legal."""
        board = chess.Board("8/K1P4r/8/8/8/8/8/7k w - - 0 1")
        result = perft(board, 1)
        # Legal: Ka8, Kb8, Ka6, Kb6, Kb7 = 5
        assert result == 5, (
            f"Pinned pawn pos perft(1) = {result}, expected 5 (king moves only)"
        )


# ── Perft comparison tool ──────────────────────────────────────────────

class TestComparisonTool:
    """The perft comparison tool must exist and be functional."""

    def test_tool_exists_and_substantial(self):
        """Comparison tool file must exist with real implementation."""
        path = "/app/perft_compare.py"
        assert os.path.exists(path), f"{path} does not exist"
        size = os.path.getsize(path)
        assert size > 500, (
            f"{path} is only {size} bytes -- too small for a real tool"
        )

    def test_tool_references_stockfish(self):
        """Tool must integrate with Stockfish for comparison."""
        with open("/app/perft_compare.py") as f:
            content = f.read().lower()
        assert "stockfish" in content, (
            "Comparison tool must reference Stockfish"
        )

    def test_tool_runs_without_crash(self):
        """Tool must execute without Python exceptions on a simple position."""
        result = subprocess.run(
            ["python3", "/app/perft_compare.py",
             "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "2"],
            capture_output=True, text=True, timeout=60
        )
        assert "Traceback" not in result.stderr, (
            f"Tool crashed with exception:\n{result.stderr[:500]}"
        )
        output = result.stdout + result.stderr
        assert len(output.strip()) > 20, (
            f"Tool output too short to be meaningful: {output[:200]}"
        )

    def test_tool_produces_chess_data(self):
        """Tool output should contain numeric perft data or move notation."""
        result = subprocess.run(
            ["python3", "/app/perft_compare.py",
             "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "2"],
            capture_output=True, text=True, timeout=60
        )
        output = result.stdout
        has_moves = bool(re.search(r'[a-h][1-8][a-h][1-8]', output))
        has_numbers = bool(re.search(r'\b\d{2,}\b', output))
        assert has_moves or has_numbers, (
            f"Tool output lacks chess data:\n{output[:500]}"
        )
