
"""
Tests for the NNUE chess evaluation module.

Verifies that /app/nnue.py produces results identical to the compiled
oracle binary at /app/nnue_oracle across a diverse set of positions.
"""

import subprocess
import sys

import pytest

sys.path.insert(0, "/app")


# ======================== Oracle helpers ========================

def _oracle_eval(fen: str) -> int:
    """Run the oracle binary and return the integer evaluation."""
    result = subprocess.run(
        ["/app/nnue_oracle", "eval"] + fen.split(),
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"Oracle failed for '{fen}': {result.stderr}"
    return int(result.stdout.strip())


def _oracle_features(fen: str):
    """Run the oracle binary and return (white_features, black_features)."""
    result = subprocess.run(
        ["/app/nnue_oracle", "features"] + fen.split(),
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"Oracle failed for '{fen}': {result.stderr}"
    lines = result.stdout.strip().split("\n")
    white_feats = [int(x) for x in lines[0].split(":")[1].split()]
    black_feats = [int(x) for x in lines[1].split(":")[1].split()]
    return white_feats, black_feats


# ======================== Test Positions ========================

TEST_POSITIONS = [
    # Starting position — both kings e-file, 32 pieces
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    # After 1.e4 — black to move, en passant square
    "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
    # White king d1 (file 3: no mirror for white), Black king e8 (file 4: mirror for black)
    "4k3/8/8/8/8/8/8/3K4 w - - 0 1",
    # Corner kings — extreme file positions
    "7k/8/8/8/8/8/8/K7 w - - 0 1",
    # Sicilian middlegame — many pieces, various piece types
    "r1bqkb1r/pp2pppp/2np1n2/6B1/3NP3/2N5/PPP2PPP/R2QKB1R b KQkq - 0 6",
    # Endgame, low halfmove clock
    "8/5k2/8/8/8/8/5K2/4R3 w - - 10 50",
    # Same endgame, high halfmove clock — tests 50-move scaling
    "8/5k2/8/8/8/8/5K2/4R3 w - - 90 100",
    # Promoted queen, corner kings
    "Q6k/8/8/8/8/8/8/K7 w - - 0 1",
    # Both kings e-file, center
    "4k3/8/8/8/8/8/8/4K3 w - - 0 1",
    # Dense position after castling
    "r1bq1rk1/ppp2ppp/2n1pn2/3p4/2PP4/2N1PN2/PP3PPP/R1BQ1RK1 w - - 0 8",
    # Black to move, kings on opposite flanks
    "1k6/8/8/8/8/8/8/6K1 b - - 0 1",
    # Italian game — one side castled
    "r1bqk2r/pppp1ppp/2n2n2/2b1p3/4P3/5N2/PPPP1PPP/RNBQ1RK1 b kq - 5 4",
    # White king g1 (file 6: mirror), black king c8 (file 2: no mirror)
    "2k5/8/8/8/8/8/8/6K1 w - - 0 1",
    # Both kings queen-side, no mirror for either
    "2k5/8/8/8/8/8/8/1K6 w - - 0 1",
    # Asymmetric pawn structure, multiple piece types
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
]


# ======================== Feature Tests ========================


class TestFeatureComputation:
    """Verify feature indices match the oracle for all test positions."""

    @pytest.mark.parametrize("fen", TEST_POSITIONS)
    def test_features_white_perspective(self, fen):
        import nnue

        expected, _ = _oracle_features(fen)
        actual = nnue.get_features(fen, True)
        assert actual == expected, (
            f"White features mismatch for:\n  {fen}\n"
            f"  expected: {expected}\n  actual:   {actual}"
        )

    @pytest.mark.parametrize("fen", TEST_POSITIONS)
    def test_features_black_perspective(self, fen):
        import nnue

        _, expected = _oracle_features(fen)
        actual = nnue.get_features(fen, False)
        assert actual == expected, (
            f"Black features mismatch for:\n  {fen}\n"
            f"  expected: {expected}\n  actual:   {actual}"
        )


# ======================== Evaluation Tests ========================


class TestEvaluation:
    """Verify evaluation scores match the oracle exactly."""

    @pytest.mark.parametrize("fen", TEST_POSITIONS)
    def test_evaluate(self, fen):
        import nnue

        expected = _oracle_eval(fen)
        actual = nnue.evaluate(fen)
        assert actual == expected, (
            f"Eval mismatch for:\n  {fen}\n"
            f"  expected: {expected}\n  actual:   {actual}"
        )


# ======================== Structural Tests ========================


class TestStructuralProperties:
    """Verify structural invariants independent of the oracle."""

    @pytest.mark.parametrize("fen", TEST_POSITIONS)
    def test_feature_count_equals_pieces(self, fen):
        import chess
        import nnue

        board = chess.Board(fen)
        num_pieces = len(board.piece_map())
        for wp in [True, False]:
            features = nnue.get_features(fen, wp)
            label = "white" if wp else "black"
            assert len(features) == num_pieces, (
                f"Feature count ({len(features)}) != piece count ({num_pieces}) "
                f"for {label} perspective of {fen}"
            )

    @pytest.mark.parametrize("fen", TEST_POSITIONS)
    def test_features_in_valid_range(self, fen):
        import nnue

        for wp in [True, False]:
            features = nnue.get_features(fen, wp)
            for f in features:
                assert 0 <= f < 768, (
                    f"Feature index {f} out of [0,767] for "
                    f"{'white' if wp else 'black'} perspective of {fen}"
                )

    @pytest.mark.parametrize("fen", TEST_POSITIONS)
    def test_no_duplicate_features(self, fen):
        import nnue

        for wp in [True, False]:
            features = nnue.get_features(fen, wp)
            assert len(features) == len(set(features)), (
                f"Duplicate feature indices for "
                f"{'white' if wp else 'black'} perspective of {fen}"
            )

    @pytest.mark.parametrize("fen", TEST_POSITIONS)
    def test_features_sorted(self, fen):
        import nnue

        for wp in [True, False]:
            features = nnue.get_features(fen, wp)
            assert features == sorted(features), (
                f"Features must be sorted for "
                f"{'white' if wp else 'black'} perspective of {fen}"
            )

    def test_evaluate_returns_int(self):
        import nnue

        fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        result = nnue.evaluate(fen)
        assert isinstance(result, int), f"evaluate() must return int, got {type(result)}"

    def test_evaluate_deterministic(self):
        import nnue

        for fen in TEST_POSITIONS:
            first = nnue.evaluate(fen)
            second = nnue.evaluate(fen)
            assert first == second, (
                f"Non-deterministic evaluation for {fen}: "
                f"first={first}, second={second}"
            )

    def test_halfmove_scaling_reduces_eval(self):
        import nnue

        fen_low = "8/5k2/8/8/8/8/5K2/4R3 w - - 0 50"
        fen_high = "8/5k2/8/8/8/8/5K2/4R3 w - - 90 100"
        eval_low = nnue.evaluate(fen_low)
        eval_high = nnue.evaluate(fen_high)
        if eval_low != 0:
            assert abs(eval_high) <= abs(eval_low), (
                f"50-move scaling failed: |eval(hmc=90)|={abs(eval_high)} > "
                f"|eval(hmc=0)|={abs(eval_low)}"
            )

    def test_mirror_boundary_features_differ(self):
        """Kings on d-file (no mirror) vs e-file (mirror) must give different features."""
        import nnue

        fen_d = "4k3/8/8/8/8/8/8/3K4 w - - 0 1"
        fen_e = "4k3/8/8/8/8/8/8/4K3 w - - 0 1"
        feat_d = nnue.get_features(fen_d, True)
        feat_e = nnue.get_features(fen_e, True)
        assert feat_d != feat_e, (
            "White features should differ between king on d1 vs e1"
        )
