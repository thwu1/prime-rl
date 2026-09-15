
import sys
sys.path.insert(0, "/app")

from nnue_features import (
    parse_fen,
    active_features,
    make_move,
    needs_refresh,
    feature_delta,
    feature_index,
    king_bucket,
)


# ─── feature_index unit tests ───────────────────────────────────────

class TestFeatureIndex:

    def test_pawn_wp_ksq2(self):
        assert feature_index(0, True, 8, True, 2) == 8

    def test_pawn_wp_ksq4(self):
        assert feature_index(0, True, 8, True, 4) == 15

    def test_king_wp_ksq4(self):
        assert feature_index(5, True, 4, True, 4) == 323

    def test_opp_king_wp_ksq4(self):
        assert feature_index(5, False, 60, True, 4) == 763

    def test_rook_bp_ksq60(self):
        assert feature_index(3, False, 56, False, 60) == 199

    def test_knight_bp_ksq60(self):
        assert feature_index(1, True, 33, False, 60) == 478

    def test_king_wp_ksq0(self):
        assert feature_index(5, True, 0, True, 0) == 320

    def test_rook_wp_ksq0(self):
        assert feature_index(3, False, 63, True, 0) == 639


# ─── king_bucket unit tests ─────────────────────────────────────────

class TestKingBucket:

    def test_white_e1(self):
        assert king_bucket(4, True) == 3

    def test_white_a1(self):
        assert king_bucket(0, True) == 0

    def test_white_h1(self):
        assert king_bucket(7, True) == 0

    def test_black_e8(self):
        assert king_bucket(60, False) == 3

    def test_black_a8(self):
        assert king_bucket(56, False) == 0

    def test_white_e5(self):
        assert king_bucket(36, True) == 6

    def test_white_a3(self):
        assert king_bucket(16, True) == 6

    def test_white_g1(self):
        assert king_bucket(6, True) == 1


# ─── active_features: starting position ─────────────────────────────

class TestActiveFeaturesStartpos:

    STARTPOS = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

    EXPECTED_WHITE = [
        8, 9, 10, 11, 12, 13, 14, 15,
        65, 70,
        130, 133,
        192, 199,
        260,
        323,
        432, 433, 434, 435, 436, 437, 438, 439,
        505, 510,
        570, 573,
        632, 639,
        700,
        763,
    ]

    def test_white_perspective_features(self):
        pos = parse_fen(self.STARTPOS)
        bucket, features = active_features(pos, True)
        assert bucket == 3
        assert features == self.EXPECTED_WHITE

    def test_black_perspective_features(self):
        pos = parse_fen(self.STARTPOS)
        bucket, features = active_features(pos, False)
        assert bucket == 3
        assert features == self.EXPECTED_WHITE

    def test_feature_count(self):
        pos = parse_fen(self.STARTPOS)
        _, features = active_features(pos, True)
        assert len(features) == 32


# ─── active_features: small positions ────────────────────────────────

class TestActiveFeaturesSimple:

    def test_two_kings_symmetric(self):
        pos = parse_fen("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
        wb, wf = active_features(pos, True)
        assert wb == 3
        assert wf == [323, 763]

        bb, bf = active_features(pos, False)
        assert bb == 3
        assert bf == [323, 763]

    def test_two_kings_asymmetric(self):
        pos = parse_fen("4k3/8/8/8/8/8/8/K7 w - - 0 1")
        wb, wf = active_features(pos, True)
        assert wb == 0
        assert wf == [320, 764]

        bb, bf = active_features(pos, False)
        assert bb == 3
        assert bf == [323, 767]

    def test_three_pieces(self):
        pos = parse_fen("4k3/8/8/8/4P3/8/8/4K3 w - - 0 1")
        wb, wf = active_features(pos, True)
        assert wb == 3
        assert wf == [27, 323, 763]

        bb, bf = active_features(pos, False)
        assert bb == 3
        assert bf == [323, 419, 763]


# ─── Consistency: make_move vs parse_fen ─────────────────────────────

class TestConsistencyRuyLopez:

    MOVES = [
        "e2e4", "e7e5", "g1f3", "b8c6", "f1b5",
        "a7a6", "b5a4", "g8f6", "e1g1", "f8e7",
    ]
    EXPECTED_FENS = [
        "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2",
        "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2",
        "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3",
        "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3",
        "r1bqkbnr/1ppp1ppp/p1n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 4",
        "r1bqkbnr/1ppp1ppp/p1n5/4p3/B3P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 1 4",
        "r1bqkb1r/1ppp1ppp/p1n2n2/4p3/B3P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 2 5",
        "r1bqkb1r/1ppp1ppp/p1n2n2/4p3/B3P3/5N2/PPPP1PPP/RNBQ1RK1 b kq - 3 5",
        "r1bqk2r/1pppbppp/p1n2n2/4p3/B3P3/5N2/PPPP1PPP/RNBQ1RK1 w kq - 4 6",
    ]

    def test_consistency(self):
        start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        pos = parse_fen(start_fen)

        for i, (move, expected_fen) in enumerate(zip(self.MOVES, self.EXPECTED_FENS)):
            pos = make_move(pos, move)
            pos_from_fen = parse_fen(expected_fen)

            for perspective in [True, False]:
                feat_move = active_features(pos, perspective)
                feat_fen = active_features(pos_from_fen, perspective)
                side = "white" if perspective else "black"
                assert feat_move == feat_fen, (
                    f"Mismatch at half-move {i+1} ({move}), {side} perspective: "
                    f"make_move={feat_move}, parse_fen={feat_fen}"
                )


class TestConsistencyEnPassant:

    MOVES = ["e2e4", "c7c5", "e4e5", "d7d5", "e5d6"]
    EXPECTED_FENS = [
        "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq c6 0 2",
        "rnbqkbnr/pp1ppppp/8/2p1P3/8/8/PPPP1PPP/RNBQKBNR b KQkq - 0 2",
        "rnbqkbnr/pp2pppp/8/2ppP3/8/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 3",
        "rnbqkbnr/pp2pppp/3P4/2p5/8/8/PPPP1PPP/RNBQKBNR b KQkq - 0 3",
    ]

    def test_consistency(self):
        pos = parse_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")

        for i, (move, expected_fen) in enumerate(zip(self.MOVES, self.EXPECTED_FENS)):
            pos = make_move(pos, move)
            pos_from_fen = parse_fen(expected_fen)

            for perspective in [True, False]:
                feat_move = active_features(pos, perspective)
                feat_fen = active_features(pos_from_fen, perspective)
                side = "white" if perspective else "black"
                assert feat_move == feat_fen, (
                    f"Mismatch at half-move {i+1} ({move}), {side} perspective"
                )


class TestConsistencyPromotion:

    def test_promotion_queen(self):
        fen_before = "4k3/3P4/8/8/8/8/8/4K3 w - - 0 1"
        fen_after = "3Qk3/8/8/8/8/8/8/4K3 b - - 0 1"
        pos = make_move(parse_fen(fen_before), "d7d8q")
        pos2 = parse_fen(fen_after)
        for p in [True, False]:
            assert active_features(pos, p) == active_features(pos2, p)

    def test_promotion_knight_capture(self):
        fen_before = "2r1k3/3P4/8/8/8/8/8/4K3 w - - 0 1"
        fen_after = "2N1k3/8/8/8/8/8/8/4K3 b - - 0 1"
        pos = make_move(parse_fen(fen_before), "d7c8n")
        pos2 = parse_fen(fen_after)
        for p in [True, False]:
            assert active_features(pos, p) == active_features(pos2, p)

    def test_promotion_rook(self):
        fen_before = "4k3/P7/8/8/8/8/8/4K3 w - - 0 1"
        fen_after = "R3k3/8/8/8/8/8/8/4K3 b - - 0 1"
        pos = make_move(parse_fen(fen_before), "a7a8r")
        pos2 = parse_fen(fen_after)
        for p in [True, False]:
            assert active_features(pos, p) == active_features(pos2, p)

    def test_black_promotion(self):
        fen_before = "4k3/8/8/8/8/8/3p4/4K3 b - - 0 1"
        fen_after = "4k3/8/8/8/8/8/8/3qK3 w - - 0 2"
        pos = make_move(parse_fen(fen_before), "d2d1q")
        pos2 = parse_fen(fen_after)
        for p in [True, False]:
            assert active_features(pos, p) == active_features(pos2, p)


# ─── needs_refresh tests ────────────────────────────────────────────

class TestNeedsRefresh:

    def test_non_king_move(self):
        pos = parse_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        assert needs_refresh(pos, "e2e4", True) is False
        assert needs_refresh(pos, "e2e4", False) is False

    def test_king_a3_to_b3(self):
        pos = parse_fen("4k3/8/8/8/8/K7/8/8 w - - 0 1")
        assert needs_refresh(pos, "a3b3", True) is False
        assert needs_refresh(pos, "a3b3", False) is False

    def test_king_d3_to_e3(self):
        pos = parse_fen("4k3/8/8/8/8/3K4/8/8 w - - 0 1")
        assert needs_refresh(pos, "d3e3", True) is True
        assert needs_refresh(pos, "d3e3", False) is False

    def test_kingside_castle(self):
        pos = parse_fen("r1bqkb1r/1ppp1ppp/p1n2n2/4p3/B3P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 2 5")
        assert needs_refresh(pos, "e1g1", True) is True
        assert needs_refresh(pos, "e1g1", False) is False

    def test_king_c1_to_d1(self):
        pos = parse_fen("4k3/8/8/8/8/8/8/2K5 w - - 0 1")
        assert needs_refresh(pos, "c1d1", True) is True

    def test_black_king_f6_to_g6(self):
        pos = parse_fen("8/8/5k2/8/8/8/8/4K3 b - - 0 1")
        assert needs_refresh(pos, "f6g6", False) is False
        assert needs_refresh(pos, "f6g6", True) is False

    def test_black_king_d6_to_e6(self):
        pos = parse_fen("8/8/3k4/8/8/8/8/4K3 b - - 0 1")
        assert needs_refresh(pos, "d6e6", False) is True
        assert needs_refresh(pos, "d6e6", True) is False


# ─── feature_delta tests ────────────────────────────────────────────

class TestFeatureDelta:

    def test_e2e4_wp(self):
        pos = parse_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        adds, subs = feature_delta(pos, "e2e4", True)
        assert adds == [27]
        assert subs == [11]

    def test_e2e4_bp(self):
        pos = parse_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        adds, subs = feature_delta(pos, "e2e4", False)
        assert adds == [419]
        assert subs == [435]

    def test_castle_opp_perspective(self):
        pos = parse_fen("r1bqkb1r/1ppp1ppp/p1n2n2/4p3/B3P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 2 5")
        adds, subs = feature_delta(pos, "e1g1", False)
        assert adds == [634, 761]
        assert subs == [632, 763]

    def test_ep_wp(self):
        pos = parse_fen("rnbqkbnr/pp2pppp/8/2ppP3/8/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 3")
        adds, subs = feature_delta(pos, "e5d6", True)
        assert adds == [44]
        assert subs == [35, 420]

    def test_ep_bp(self):
        pos = parse_fen("rnbqkbnr/pp2pppp/8/2ppP3/8/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 3")
        adds, subs = feature_delta(pos, "e5d6", False)
        assert adds == [404]
        assert subs == [28, 411]

    def test_promo_wp(self):
        pos = parse_fen("4k3/3P4/8/8/8/8/8/4K3 w - - 0 1")
        adds, subs = feature_delta(pos, "d7d8q", True)
        assert adds == [316]
        assert subs == [52]

    def test_promo_bp(self):
        pos = parse_fen("4k3/3P4/8/8/8/8/8/4K3 w - - 0 1")
        adds, subs = feature_delta(pos, "d7d8q", False)
        assert adds == [644]
        assert subs == [396]

    def test_promo_capture_wp(self):
        pos = parse_fen("2r1k3/3P4/8/8/8/8/8/4K3 w - - 0 1")
        adds, subs = feature_delta(pos, "d7c8n", True)
        assert adds == [125]
        assert subs == [52, 637]

    def test_promo_capture_bp(self):
        pos = parse_fen("2r1k3/3P4/8/8/8/8/8/4K3 w - - 0 1")
        adds, subs = feature_delta(pos, "d7c8n", False)
        assert adds == [453]
        assert subs == [197, 396]


# ─── Feature delta + active_features consistency ────────────────────

class TestDeltaConsistency:

    def _check_delta(self, fen, move, perspective):
        pos = parse_fen(fen)
        if needs_refresh(pos, move, perspective):
            return
        old_bucket, old_feats = active_features(pos, perspective)
        adds, subs = feature_delta(pos, move, perspective)
        new_pos = make_move(pos, move)
        new_bucket, new_feats = active_features(new_pos, perspective)
        computed = sorted(set(old_feats) - set(subs) | set(adds))
        assert computed == new_feats, (
            f"Delta mismatch for {fen} + {move}, "
            f"{'white' if perspective else 'black'}: "
            f"expected {new_feats}, got {computed}"
        )

    def test_standard_moves(self):
        fens_moves = [
            ("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "e2e4"),
            ("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1", "e7e5"),
            ("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2", "g1f3"),
            ("rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2", "b8c6"),
        ]
        for fen, move in fens_moves:
            for p in [True, False]:
                self._check_delta(fen, move, p)

    def test_en_passant(self):
        self._check_delta(
            "rnbqkbnr/pp2pppp/8/2ppP3/8/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 3",
            "e5d6", True
        )
        self._check_delta(
            "rnbqkbnr/pp2pppp/8/2ppP3/8/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 3",
            "e5d6", False
        )

    def test_castling_opponent(self):
        self._check_delta(
            "r1bqkb1r/1ppp1ppp/p1n2n2/4p3/B3P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 2 5",
            "e1g1", False
        )

    def test_promotions(self):
        self._check_delta("4k3/3P4/8/8/8/8/8/4K3 w - - 0 1", "d7d8q", True)
        self._check_delta("4k3/3P4/8/8/8/8/8/4K3 w - - 0 1", "d7d8q", False)
        self._check_delta("2r1k3/3P4/8/8/8/8/8/4K3 w - - 0 1", "d7c8n", True)
        self._check_delta("2r1k3/3P4/8/8/8/8/8/4K3 w - - 0 1", "d7c8n", False)


# ─── Captures ────────────────────────────────────────────────────────

class TestCaptures:

    def test_pawn_capture(self):
        fen = "4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1"
        after_fen = "4k3/8/8/3P4/8/8/8/4K3 b - - 0 1"
        pos = make_move(parse_fen(fen), "e4d5")
        pos2 = parse_fen(after_fen)
        for p in [True, False]:
            assert active_features(pos, p) == active_features(pos2, p)

    def test_piece_capture(self):
        fen = "4k3/8/2n5/1B6/8/8/8/4K3 w - - 0 1"
        after_fen = "4k3/8/2B5/8/8/8/8/4K3 b - - 0 1"
        pos = make_move(parse_fen(fen), "b5c6")
        pos2 = parse_fen(after_fen)
        for p in [True, False]:
            assert active_features(pos, p) == active_features(pos2, p)


# ─── Queenside castling ─────────────────────────────────────────────

class TestQueensideCastling:

    def test_white_queenside(self):
        fen = "r3kbnr/pppqpppp/2n5/3p1b2/3P1B2/2N5/PPPQPPPP/R3KBNR w KQkq - 6 5"
        after_fen = "r3kbnr/pppqpppp/2n5/3p1b2/3P1B2/2N5/PPPQPPPP/2KR1BNR b kq - 7 5"
        pos = make_move(parse_fen(fen), "e1c1")
        pos2 = parse_fen(after_fen)
        for p in [True, False]:
            assert active_features(pos, p) == active_features(pos2, p)

    def test_black_queenside(self):
        fen = "r3kbnr/pppqpppp/2n5/3p1b2/3P1B2/2NQ4/PPP1PPPP/2KR1BNR b kq - 7 5"
        after_fen = "2kr1bnr/pppqpppp/2n5/3p1b2/3P1B2/2NQ4/PPP1PPPP/2KR1BNR w - - 8 6"
        pos = make_move(parse_fen(fen), "e8c8")
        pos2 = parse_fen(after_fen)
        for p in [True, False]:
            assert active_features(pos, p) == active_features(pos2, p)


# ─── Longer game ─────────────────────────────────────────────────────

class TestLongerGame:

    def test_kings_gambit_declined(self):
        moves = [
            "e2e4", "e7e5", "f2f4", "f8c5", "g1f3",
            "d7d6", "f1c4", "g8f6", "d2d3", "e8g8",
        ]
        expected_fens = [
            "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
            "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2",
            "rnbqkbnr/pppp1ppp/8/4p3/4PP2/8/PPPP2PP/RNBQKBNR b KQkq f3 0 2",
            "rnbqk1nr/pppp1ppp/8/2b1p3/4PP2/8/PPPP2PP/RNBQKBNR w KQkq - 1 3",
            "rnbqk1nr/pppp1ppp/8/2b1p3/4PP2/5N2/PPPP2PP/RNBQKB1R b KQkq - 2 3",
            "rnbqk1nr/ppp2ppp/3p4/2b1p3/4PP2/5N2/PPPP2PP/RNBQKB1R w KQkq - 0 4",
            "rnbqk1nr/ppp2ppp/3p4/2b1p3/2B1PP2/5N2/PPPP2PP/RNBQK2R b KQkq - 1 4",
            "rnbqk2r/ppp2ppp/3p1n2/2b1p3/2B1PP2/5N2/PPPP2PP/RNBQK2R w KQkq - 2 5",
            "rnbqk2r/ppp2ppp/3p1n2/2b1p3/2B1PP2/3P1N2/PPP3PP/RNBQK2R b KQkq - 0 5",
            "rnbq1rk1/ppp2ppp/3p1n2/2b1p3/2B1PP2/3P1N2/PPP3PP/RNBQK2R w KQ - 1 6",
        ]

        pos = parse_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        for i, (move, expected_fen) in enumerate(zip(moves, expected_fens)):
            pos = make_move(pos, move)
            pos2 = parse_fen(expected_fen)
            for p in [True, False]:
                f1 = active_features(pos, p)
                f2 = active_features(pos2, p)
                side = "white" if p else "black"
                assert f1 == f2, f"Mismatch at move {i+1} ({move}), {side}"
