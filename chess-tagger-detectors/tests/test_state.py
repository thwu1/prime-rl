
import sys
sys.path.insert(0, '/app')

import pytest
import chess
from chess import Board, Move
from chess.pgn import Game, GameNode
from model import Puzzle
from tagger import (
    fork, skewer, discovered_attack,
    pin_prevents_attack, pin_prevents_escape,
    back_rank_mate, smothered_mate, trapped_piece
)


def make(id: str, fen: str, line: str, cp: int = 999999998) -> Puzzle:
    """Create a Puzzle from FEN and move line (space-separated UCI moves)."""
    board = Board(fen)
    node: GameNode = Game.from_board(board)
    for uci in line.split(' '):
        move = Move.from_uci(uci)
        node = node.add_main_variation(move)
    return Puzzle(id, node.game(), cp)


# ===================== FORK TESTS =====================

class TestFork:
    def test_knight_fork_king_queen(self):
        p = make("0PQep",
                 "6q1/p6p/6p1/4k3/1P2N3/2B2P2/4K1P1/8 b - - 3 43",
                 "e5d5 e4f6 d5c4 f6g8")
        assert fork(p) is True

    def test_knight_fork_complex(self):
        p = make("1NxIN",
                 "r3k2r/p2q1ppp/4pn2/1Qp5/8/4P3/PP1N1PPP/R3K2R w KQkq - 2 16",
                 "b5c5 d7d2 e1d2 f6e4 d2e2 e4c5")
        assert fork(p) is True

    def test_not_fork_pawn_capture(self):
        p = make("6ppA2",
                 "8/p7/1p6/2p5/P6P/2P2Nk1/1r4P1/4R1K1 w - - 1 39",
                 "f3d2 b2d2 h4h5 d2g2")
        assert fork(p) is False

    def test_not_fork_exchange(self):
        p = make("bypCs",
                 "rnbq1b1r/p1k1pQp1/2p4p/1p1nP1p1/2pP4/2N3B1/PP3P1P/R3KBNR w KQ - 5 14",
                 "c3d5 d8d5 f7d5 c6d5")
        assert fork(p) is False


# ===================== SKEWER TESTS =====================

class TestSkewer:
    def test_rook_skewer(self):
        p = make("29HGS",
                 "3r4/6p1/5r1p/7k/3N1P2/3K2P1/3R4/3R4 w - - 1 50",
                 "d2e2 d8d4 d3d4 f6d6 d4e5 d6d1")
        assert skewer(p) is True

    def test_bishop_skewer(self):
        p = make("tipFF",
                 "1rr5/3k4/3bpp2/q5p1/PpRP3p/1P3N1P/1K1Q1PP1/7R w - - 2 25",
                 "h1c1 d6f4 d2d3 f4c1")
        assert skewer(p) is True

    def test_not_skewer(self):
        p = make("aUuGJ",
                 "5R2/p2rkpKp/1p2p1p1/4P1P1/8/8/P7/8 b - - 9 47",
                 "a7a5 f8f7 e7e8 f7d7 e8d7 g7h7 b6b5 h7g6")
        assert skewer(p) is False


# ===================== DISCOVERED ATTACK TESTS =====================

class TestDiscoveredAttack:
    def test_discovered_attack_bishop(self):
        p = make("01Y7w",
                 "r2q1rk1/pppb1pbp/2n1pnp1/1BPpB3/3P4/4PN2/PP3PPP/RN1QK2R w KQ - 3 9",
                 "e1g1 c6e5 d4e5 d7b5")
        assert discovered_attack(p) is True

    def test_discovered_attack_rook(self):
        p = make("07jQK",
                 "r4rk1/p1p1qppp/3b4/4n3/Q7/2NP4/PP3PPP/R1B2RK1 w - - 0 16",
                 "f1e1 e5f3 g2f3 e7e1")
        assert discovered_attack(p) is True

    def test_not_discovered_direct(self):
        p = make("0e7Q3",
                 "5rk1/2pqnrpp/p3p1b1/N3P3/1PRPPp2/P4Q2/3B1RPP/6K1 w - - 3 30",
                 "d2f4 f7f4 f3f4 f8f4")
        assert discovered_attack(p) is False

    def test_not_discovered_recapture(self):
        p = make("m3h3k",
                 "2r3k1/1r2pp1p/bqNp2p1/3P4/1p2P3/4bN2/1P4PP/2RQR2K w - - 0 24",
                 "c6e7 b7e7 c1c8 a6c8")
        assert discovered_attack(p) is False


# ===================== PIN PREVENTS ATTACK TESTS =====================

class TestPinPreventsAttack:
    def test_pin_prevents_queen_attack(self):
        p = make("P2D4h",
                 "2k5/p7/bpq1p3/8/2PP2P1/1K2P1p1/4Q1P1/8 b - - 4 36",
                 "a6c4 e2c4 c6c4 b3c4")
        assert pin_prevents_attack(p) is True

    def test_pin_prevents_piece_attack(self):
        p = make("aJPsJ",
                 "r2q1r1k/pp3pp1/2p2n1p/3PB2b/3P4/1B5P/P1PQ1PP1/R3R1K1 b - - 0 18",
                 "f6d5 d2h6 h8g8 h6g7")
        assert pin_prevents_attack(p) is True

    def test_not_pin_attack_but_escape(self):
        p = make("9CkIh",
                 "r4r2/pp3pkp/2p5/3pPp1q/3p1P2/3Q1R2/PPP3PP/R5K1 b - - 3 18",
                 "c6c5 f3h3 h5g6 h3g3 g7h8 g3g6")
        assert pin_prevents_attack(p) is False


# ===================== PIN PREVENTS ESCAPE TESTS =====================

class TestPinPreventsEscape:
    def test_pin_prevents_king_area_escape(self):
        p = make("9CkIh",
                 "r4r2/pp3pkp/2p5/3pPp1q/3p1P2/3Q1R2/PPP3PP/R5K1 b - - 3 18",
                 "c6c5 f3h3 h5g6 h3g3 g7h8 g3g6")
        assert pin_prevents_escape(p) is True

    def test_pin_prevents_rook_escape(self):
        p = make("0CR44",
                 "r2q4/4b1kp/6p1/2ppPr2/3P4/2P2N2/P4RQP/R5K1 w - - 0 27",
                 "f3d2 f5g5 d2f3 g5g2")
        assert pin_prevents_escape(p) is True

    def test_not_pin_escape_but_attack(self):
        p = make("P2D4h",
                 "2k5/p7/bpq1p3/8/2PP2P1/1K2P1p1/4Q1P1/8 b - - 4 36",
                 "a6c4 e2c4 c6c4 b3c4")
        assert pin_prevents_escape(p) is False


# ===================== BACK RANK MATE TESTS =====================

class TestBackRankMate:
    def test_back_rank_mate_rook(self):
        p = make("tMEri",
                 "5r1k/4q1p1/p2pP2p/1p6/1P2Q3/PB6/1BP3PP/6K1 w - - 1 27",
                 "e4g6 e7a7 b2d4 a7d4 g1h1 f8f1")
        assert back_rank_mate(p) is True

    def test_back_rank_mate_rook_after_queen_sac(self):
        p = make("LYKY0",
                 "r5k1/pQ3ppp/8/8/B1pp4/4q3/PP5P/5R1K b - - 0 26",
                 "a8d8 b7f7 g8h8 f7f8 d8f8 f1f8")
        assert back_rank_mate(p) is True

    def test_not_back_rank_enemy_piece_blocks(self):
        p = make("ABCL2",
                 "3r2k1/1b4pp/1p2pr2/p5N1/8/PP2n1P1/1BR2bBP/4R2K w - - 1 27",
                 "b2f6 b7g2")
        assert back_rank_mate(p) is False


# ===================== SMOTHERED MATE TESTS =====================

class TestSmotheredMate:
    def test_smothered_mate_knight(self):
        p = make("smother1",
                 "5r1k/6pp/7N/8/8/4q3/Q7/6K1 b - - 0 1",
                 "e3a3 a2g8 f8g8 h6f7")
        assert smothered_mate(p) is True

    def test_not_smothered_rook_mate(self):
        p = make("notsmother",
                 "6k1/5ppp/8/8/8/8/8/R3K3 b - - 0 1",
                 "g8h8 a1a8")
        assert smothered_mate(p) is False


# ===================== TRAPPED PIECE TESTS =====================

class TestTrappedPiece:
    def test_trapped_queen(self):
        p = make("nPqjh",
                 "r4rk1/pp1nppbp/3p1n2/q4p2/8/N1P1PP2/PP1BB1PP/2RQ1RK1 b - - 0 13",
                 "b7b6 e2b5 a7a6 c3c4 a5a3 b2a3")
        assert trapped_piece(p) is True

    def test_trapped_queen_h1(self):
        p = make("pqkqG",
                 "rnb1k2r/ppppqppp/8/2b4n/4P1N1/2N5/PPPP1PPP/R1BQKB1R w KQkq - 3 6",
                 "f2f3 e7h4 g2g3 h5g3 h2g3 h4h1")
        assert trapped_piece(p) is True

    def test_not_trapped_escapes(self):
        p = make("pjqyb",
                 "r1b1k3/1pp4R/3p4/p2P4/2P5/8/PP2pKPP/8 b - - 1 34",
                 "c8f5 h7h8 e8e7 h8a8 e2e1q f2e1")
        assert trapped_piece(p) is False

    def test_not_trapped_equal_exchange(self):
        p = make("2NQ68",
                 "3qr1k1/p5pp/1p3n2/3p2P1/2rQ4/5B1P/PBb2P2/2R2RK1 w - - 1 21",
                 "f3d5 d8d5 d4d5 f6d5")
        assert trapped_piece(p) is False
