"""Tests for KRK endgame tablebase generator."""

import pytest
import json
import os
import sys
import random
import importlib.util


def _load_module():
    spec = importlib.util.spec_from_file_location("krk_tablebase", "/app/krk_tablebase.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.generate()
    return mod


@pytest.fixture(scope="session")
def mod():
    return _load_module()


@pytest.fixture(scope="session")
def results():
    with open("/app/krk_results.json") as f:
        return json.load(f)


# ──────────────────────────────────────────────
#  Structure and consistency tests
# ──────────────────────────────────────────────

def test_results_file_exists():
    assert os.path.exists("/app/krk_results.json"), "krk_results.json not found"


def test_required_fields(results):
    for field in ["total_positions", "white_wins", "draws", "max_dtm_plies",
                   "remaining_unknown"]:
        assert field in results, f"Missing field: {field}"


def test_wins_plus_draws_equals_total(results):
    assert results["total_positions"] == results["white_wins"] + results["draws"]


def test_all_positions_resolved(results):
    assert results["remaining_unknown"] == 0, \
        f"Expected 0 unknown, got {results['remaining_unknown']}"


def test_total_positions_exact(results):
    assert results["total_positions"] == 399112, \
        f"Expected 399112 total positions, got {results['total_positions']}"


def test_white_wins_exact(results):
    assert results["white_wins"] == 376868, \
        f"Expected 376868 white wins, got {results['white_wins']}"


def test_draws_exact(results):
    assert results["draws"] == 22244, \
        f"Expected 22244 draws, got {results['draws']}"


def test_max_dtm_exact(results):
    assert results["max_dtm_plies"] == 32, \
        f"Expected max DTM 32 plies, got {results['max_dtm_plies']}"


# ──────────────────────────────────────────────
#  Specific position tests (known ground truth)
# ──────────────────────────────────────────────

def test_checkmate_dtm_zero(mod):
    """Checkmate position: WK=f6 WR=h8 BK=h6 BTM -> DTM=0."""
    assert mod.lookup_fen("7R/8/5K1k/8/8/8/8/8 b - - 0 1") == 0


def test_mate_in_one(mod):
    """WK=f6 WR=a8 BK=h6 WTM -> Rh8# -> DTM=1."""
    assert mod.lookup_fen("R7/8/5K1k/8/8/8/8/8 w - - 0 1") == 1


def test_stalemate_is_draw(mod):
    """WK=f7 WR=g7 BK=h8 BTM -> stalemate -> DTM=-1."""
    assert mod.lookup_fen("7k/5KR1/8/8/8/8/8/8 b - - 0 1") == -1


def test_rook_capture_is_draw(mod):
    """WK=a1 WR=d5 BK=e5 BTM -> BK captures rook -> DTM=-1."""
    assert mod.lookup_fen("8/8/8/3Rk3/8/8/8/K7 b - - 0 1") == -1


def test_another_checkmate(mod):
    """WK=g6 WR=a8 BK=h8 BTM -> checkmate."""
    assert mod.lookup_fen("R6k/8/6K1/8/8/8/8/8 b - - 0 1") == 0


def test_winning_btm_position(mod):
    """A BTM position where black is forced to lose (not a draw)."""
    dtm = mod.lookup_fen("7R/8/5K2/7k/8/8/8/8 b - - 0 1")
    assert dtm >= 2


def test_wtm_winning_position(mod):
    """A WTM position that is a win (DTM >= 1)."""
    dtm = mod.lookup_fen("8/8/8/8/8/1K6/R7/7k w - - 0 1")
    assert dtm >= 1


# ──────────────────────────────────────────────
#  Cross-validation with python-chess
# ──────────────────────────────────────────────

def test_verify_checkmate_with_chess_lib():
    import chess
    board = chess.Board("7R/8/5K1k/8/8/8/8/8 b - - 0 1")
    assert board.is_checkmate(), "python-chess should confirm this is checkmate"


def test_verify_stalemate_with_chess_lib():
    import chess
    board = chess.Board("7k/5KR1/8/8/8/8/8/8 b - - 0 1")
    assert board.is_stalemate(), "python-chess should confirm this is stalemate"


def test_verify_rook_capturable_with_chess_lib():
    import chess
    board = chess.Board("8/8/8/3Rk3/8/8/8/K7 b - - 0 1")
    captures = [m for m in board.legal_moves if board.is_capture(m)]
    assert len(captures) > 0, "BK should be able to capture the rook"


def test_verify_another_checkmate_with_chess_lib():
    import chess
    board = chess.Board("R6k/8/6K1/8/8/8/8/8 b - - 0 1")
    assert board.is_checkmate(), "python-chess should confirm this is checkmate"


# ──────────────────────────────────────────────
#  DTM self-consistency checks
# ──────────────────────────────────────────────

def test_wtm_consistency_best_move_leads_to_dtm_minus_one(mod):
    """For WTM winning positions, the best legal move must lead to DTM-1."""
    import chess

    test_fens = [
        "R7/8/5K1k/8/8/8/8/8 w - - 0 1",
        "8/8/8/8/8/1K6/R7/7k w - - 0 1",
        "8/8/8/4K3/R7/8/8/7k w - - 0 1",
        "1R6/8/3K4/8/8/8/8/7k w - - 0 1",
    ]

    for fen in test_fens:
        dtm = mod.lookup_fen(fen)
        if dtm <= 0:
            continue

        board = chess.Board(fen)
        min_succ = float('inf')

        for move in board.legal_moves:
            board.push(move)
            sf = board.fen()
            board.pop()
            try:
                sd = mod.lookup_fen(sf)
                if 0 <= sd < min_succ:
                    min_succ = sd
            except (ValueError, KeyError):
                pass

        assert min_succ == dtm - 1, \
            f"WTM consistency: {fen} DTM={dtm} but best successor DTM={min_succ}"


def test_btm_consistency_all_moves_resolved(mod):
    """For BTM winning positions, ALL KRK-internal moves lead to WTM wins."""
    import chess

    test_fens = [
        "7R/8/5K2/7k/8/8/8/8 b - - 0 1",
        "R7/8/5K2/8/7k/8/8/8 b - - 0 1",
        "7R/8/8/5K2/8/7k/8/8 b - - 0 1",
    ]

    for fen in test_fens:
        dtm = mod.lookup_fen(fen)
        if dtm <= 0:
            continue

        board = chess.Board(fen)
        max_succ = -1

        for move in board.legal_moves:
            board.push(move)
            sf = board.fen()
            board.pop()
            try:
                sd = mod.lookup_fen(sf)
                if sd >= 0 and sd > max_succ:
                    max_succ = sd
            except (ValueError, KeyError):
                pass

        if max_succ >= 0:
            assert dtm == max_succ + 1, \
                f"BTM consistency: {fen} DTM={dtm} but max successor DTM={max_succ}"


# ──────────────────────────────────────────────
#  Random sampling cross-validation
# ──────────────────────────────────────────────

def _sq_to_rank_file(sq):
    return sq // 8, sq % 8


def _build_fen(wk, wr, bk, stm):
    board_arr = ['.'] * 64
    board_arr[wk] = 'K'
    board_arr[wr] = 'R'
    board_arr[bk] = 'k'
    ranks = []
    for rank in range(7, -1, -1):
        row = ''
        empty = 0
        for file in range(8):
            sq = rank * 8 + file
            if board_arr[sq] == '.':
                empty += 1
            else:
                if empty:
                    row += str(empty)
                    empty = 0
                row += board_arr[sq]
        if empty:
            row += str(empty)
        ranks.append(row)
    return '/'.join(ranks) + ' ' + ('w' if stm == 0 else 'b') + ' - - 0 1'


def test_random_positions_checkmate_stalemate(mod):
    """Sample random BTM positions and cross-validate checkmate/stalemate with python-chess."""
    import chess

    rng = random.Random(12345)
    checked = 0
    total_valid = 0

    for _ in range(20000):
        wk = rng.randint(0, 63)
        wr = rng.randint(0, 63)
        if wr == wk:
            continue
        bk = rng.randint(0, 63)
        if bk == wk or bk == wr:
            continue
        r1, f1 = _sq_to_rank_file(wk)
        r2, f2 = _sq_to_rank_file(bk)
        if max(abs(r1 - r2), abs(f1 - f2)) <= 1:
            continue

        fen = _build_fen(wk, wr, bk, 1)  # BTM
        try:
            dtm = mod.lookup_fen(fen)
        except (ValueError, KeyError):
            continue

        total_valid += 1
        board = chess.Board(fen)
        if board.is_checkmate():
            assert dtm == 0, f"Checkmate at {fen} should have DTM=0, got {dtm}"
            checked += 1
        elif board.is_stalemate():
            assert dtm == -1, f"Stalemate at {fen} should be draw (-1), got {dtm}"
            checked += 1
        else:
            assert dtm != 0, f"Non-checkmate {fen} should not have DTM=0"

    assert total_valid >= 100, f"Too few valid positions sampled ({total_valid})"
    assert checked >= 1, f"No checkmates/stalemates found in {total_valid} samples"


def test_random_wtm_positions_not_draw_when_winning(mod):
    """Sample random WTM positions and verify wins/draws are reasonable."""
    import chess

    rng = random.Random(54321)
    wins = 0
    draws = 0

    for _ in range(2000):
        wk = rng.randint(0, 63)
        wr = rng.randint(0, 63)
        if wr == wk:
            continue
        bk = rng.randint(0, 63)
        if bk == wk or bk == wr:
            continue
        r1, f1 = _sq_to_rank_file(wk)
        r2, f2 = _sq_to_rank_file(bk)
        if max(abs(r1 - r2), abs(f1 - f2)) <= 1:
            continue

        fen = _build_fen(wk, wr, bk, 0)  # WTM
        try:
            dtm = mod.lookup_fen(fen)
        except (ValueError, KeyError):
            continue

        if dtm >= 0:
            wins += 1
        else:
            draws += 1

    assert wins > 0, "Should have winning WTM positions"


def test_rook_capture_draws_random_sample(mod):
    """Sample positions where BK is adjacent to unprotected WR and verify they are draws."""
    import chess

    rng = random.Random(99999)
    checked = 0

    for _ in range(5000):
        wk = rng.randint(0, 63)
        wr = rng.randint(0, 63)
        if wr == wk:
            continue
        # Ensure WK does NOT protect WR (not adjacent)
        r_wk, f_wk = _sq_to_rank_file(wk)
        r_wr, f_wr = _sq_to_rank_file(wr)
        if max(abs(r_wk - r_wr), abs(f_wk - f_wr)) <= 1:
            continue
        # Place BK adjacent to WR (can capture)
        for dr in [-1, 0, 1]:
            for df in [-1, 0, 1]:
                if dr == 0 and df == 0:
                    continue
                nr, nf = r_wr + dr, f_wr + df
                if not (0 <= nr < 8 and 0 <= nf < 8):
                    continue
                bk = nr * 8 + nf
                if bk == wk or bk == wr:
                    continue
                if max(abs(r_wk - nr), abs(f_wk - nf)) <= 1:
                    continue
                fen = _build_fen(wk, wr, bk, 1)  # BTM
                try:
                    dtm = mod.lookup_fen(fen)
                except (ValueError, KeyError):
                    continue
                # BK can capture unprotected rook -> must be draw
                assert dtm == -1, \
                    f"BK adjacent to unprotected WR at {fen} should be draw, got DTM={dtm}"
                checked += 1

    assert checked >= 50, f"Too few rook-capture positions verified ({checked})"
