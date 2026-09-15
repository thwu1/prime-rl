"""
Reference solver and tests for FairKalah Retrograde Solver Pipeline.
Independent implementation — does not import from /app/.
"""

import json
import os
import sys
import sqlite3
import math
import pytest

sys.setrecursionlimit(500000)


# ---------------------------------------------------------------------------
# Reference Kalah engine
# ---------------------------------------------------------------------------

class RefKalah:
    def __init__(self, n, board=None, seeds=None, side=0):
        self.n = n
        self.side = side
        if board is not None:
            self.board = list(board)
        else:
            self.board = [0] * (2 * (n + 1))
            if seeds is not None:
                for i in range(n):
                    self.board[i] = seeds
                    self.board[n + 1 + i] = seeds

    def clone(self):
        s = RefKalah.__new__(RefKalah)
        s.n = self.n
        s.side = self.side
        s.board = list(self.board)
        return s

    def key(self):
        return (tuple(self.board), self.side)

    def legal_moves(self):
        if self.side == 0:
            return [i for i in range(self.n) if self.board[i] > 0]
        else:
            return [i for i in range(self.n + 1, 2 * self.n + 1)
                    if self.board[i] > 0]

    def is_terminal(self):
        se = all(self.board[i] == 0 for i in range(self.n))
        ne = all(self.board[i] == 0
                 for i in range(self.n + 1, 2 * self.n + 1))
        return se or ne

    def terminal_score(self):
        s = self.board[self.n]
        ns = self.board[2 * self.n + 1]
        for i in range(self.n):
            s += self.board[i]
        for i in range(self.n + 1, 2 * self.n + 1):
            ns += self.board[i]
        return s - ns

    def make_move(self, pit, captures=True):
        n = self.n
        stones = self.board[pit]
        self.board[pit] = 0
        total = 2 * (n + 1)
        opp_store = (2 * n + 1) if self.side == 0 else n
        own_store = n if self.side == 0 else (2 * n + 1)

        idx = pit
        for _ in range(stones):
            idx = (idx + 1) % total
            if idx == opp_store:
                idx = (idx + 1) % total
            self.board[idx] += 1

        if idx == own_store:
            return True

        if captures:
            if self.side == 0:
                is_own = 0 <= idx < n
            else:
                is_own = n + 1 <= idx <= 2 * n
            if is_own and self.board[idx] == 1:
                opp = 2 * n - idx
                if self.board[opp] > 0:
                    self.board[own_store] += self.board[idx] + self.board[opp]
                    self.board[idx] = 0
                    self.board[opp] = 0

        self.side = 1 - self.side
        return False


# ---------------------------------------------------------------------------
# Reference solver (minimax with memoization)
# ---------------------------------------------------------------------------

def _ref_minimax(state, captures, tt):
    key = state.key()
    if key in tt:
        return tt[key]

    if state.is_terminal():
        v = state.terminal_score()
        tt[key] = (v, -1)
        return v, -1

    moves = state.legal_moves()
    best_move = moves[0]

    if state.side == 0:
        best = -9999
        for m in moves:
            c = state.clone()
            c.make_move(m, captures)
            v, _ = _ref_minimax(c, captures, tt)
            if v > best:
                best = v
                best_move = m
    else:
        best = 9999
        for m in moves:
            c = state.clone()
            c.make_move(m, captures)
            v, _ = _ref_minimax(c, captures, tt)
            if v < best:
                best = v
                best_move = m

    tt[key] = (best, best_move)
    return best, best_move


# ---------------------------------------------------------------------------
# Pie-rule analysis
# ---------------------------------------------------------------------------

def _enum_first_turn(state, captures, seq, results):
    for m in state.legal_moves():
        child = state.clone()
        extra = child.make_move(m, captures)
        new_seq = seq + [m]
        if extra and not child.is_terminal() and child.legal_moves():
            _enum_first_turn(child, captures, new_seq, results)
        else:
            results.append((child, new_seq))


def _ref_pie_value(state, captures, tt=None):
    if tt is None:
        tt = {}
    outcomes = []
    _enum_first_turn(state, captures, [], outcomes)

    best_pie = -9999
    best_seq = None

    for child, seq in outcomes:
        if child.is_terminal():
            val = child.terminal_score()
        else:
            val, _ = _ref_minimax(child, captures, tt)

        if val > 0:
            south_gets = -val
        elif val < 0:
            south_gets = val
        else:
            south_gets = 0

        if south_gets > best_pie:
            best_pie = south_gets
            best_seq = seq

    return best_pie, best_seq


# ---------------------------------------------------------------------------
# Enumerate all distributions of total stones into num_pos positions
# ---------------------------------------------------------------------------

def _enumerate_distributions(total, num_pos):
    if num_pos == 1:
        yield (total,)
        return
    for k in range(total + 1):
        for rest in _enumerate_distributions(total - k, num_pos - 1):
            yield (k,) + rest


# ---------------------------------------------------------------------------
# Helper to build state from position JSON
# ---------------------------------------------------------------------------

def _make_state(pos):
    n = pos["pits_per_side"]
    board = [0] * (2 * (n + 1))
    for i, v in enumerate(pos["south_pits"]):
        board[i] = v
    board[n] = pos["south_store"]
    for i, v in enumerate(pos["north_pits"]):
        board[n + 1 + i] = v
    board[2 * n + 1] = pos["north_store"]
    side = 0 if pos["side_to_move"] == "south" else 1
    return RefKalah(n, board=board, side=side)


# ---------------------------------------------------------------------------
# Stars-and-bars count: C(total + num_pos - 1, num_pos - 1)
# ---------------------------------------------------------------------------

def _comb(n, k):
    return math.comb(n, k)


def _expected_distributions(total_stones, num_pos):
    return _comb(total_stones + num_pos - 1, num_pos - 1)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ref_data():
    """Compute reference values for all positions."""
    with open("/app/positions.json") as f:
        positions = json.load(f)
    with open("/app/results.json") as f:
        results = json.load(f)

    refs = {}
    for pos in positions:
        pid = pos["id"]
        state = _make_state(pos)

        std_tt = {}
        std_val, _ = _ref_minimax(state.clone(), True, std_tt)

        fair_tt = {}
        fair_val, _ = _ref_minimax(state.clone(), False, fair_tt)

        if pos["side_to_move"] == "south":
            pie_val, _ = _ref_pie_value(state.clone(), False, fair_tt)
        else:
            pie_val = None

        refs[pid] = dict(
            state=state, pos=pos,
            std_val=std_val, std_tt=std_tt,
            fair_val=fair_val, fair_tt=fair_tt,
            pie_val=pie_val,
        )

    return positions, results, refs


@pytest.fixture(scope="module")
def ref_balance():
    """Compute reference balance statistics by solving all states."""
    stats = {}
    for seeds in [1, 2]:
        n = 3
        total_stones = 2 * n * seeds
        num_pos = 2 * (n + 1)

        for captures in [True, False]:
            variant = "standard" if captures else "fairkalah"
            tt = {}
            south_win = 0
            draw = 0
            north_win = 0
            total = 0

            for dist in _enumerate_distributions(total_stones, num_pos):
                state = RefKalah(n, board=list(dist), side=0)
                val, _ = _ref_minimax(state, captures, tt)
                total += 1
                if val > 0:
                    south_win += 1
                elif val == 0:
                    draw += 1
                else:
                    north_win += 1

            key = f"{n}_{seeds}_{variant}"
            stats[key] = {
                "south_win_frac": round(south_win / total, 6),
                "draw_frac": round(draw / total, 6),
                "north_win_frac": round(north_win / total, 6),
                "total_positions": total,
            }
    return stats


# ---------------------------------------------------------------------------
# Tests: Results file
# ---------------------------------------------------------------------------

def test_results_file_exists():
    assert os.path.exists("/app/results.json"), "/app/results.json not found"


def test_results_format(ref_data):
    positions, results, refs = ref_data
    assert "positions" in results, "Missing 'positions' key"
    assert "balance" in results, "Missing 'balance' key"

    required = [
        "standard_value", "standard_best_move",
        "fairkalah_value", "fairkalah_best_move",
        "pie_rule_value", "pie_rule_first_moves",
    ]
    for pos in positions:
        pid = pos["id"]
        assert pid in results["positions"], f"Missing result for {pid}"
        for k in required:
            assert k in results["positions"][pid], \
                f"Missing key '{k}' in result for {pid}"


# ---------------------------------------------------------------------------
# Tests: Compiled library
# ---------------------------------------------------------------------------

def test_compiled_library_exists():
    assert os.path.exists("/app/libkalah.so"), \
        "/app/libkalah.so not found — C library must be compiled"


# ---------------------------------------------------------------------------
# Tests: Game values
# ---------------------------------------------------------------------------

def test_standard_values(ref_data):
    positions, results, refs = ref_data
    for pos in positions:
        pid = pos["id"]
        expected = refs[pid]["std_val"]
        actual = results["positions"][pid]["standard_value"]
        assert actual == expected, \
            f"{pid}: standard_value {actual} != expected {expected}"


def test_fairkalah_values(ref_data):
    positions, results, refs = ref_data
    for pos in positions:
        pid = pos["id"]
        expected = refs[pid]["fair_val"]
        actual = results["positions"][pid]["fairkalah_value"]
        assert actual == expected, \
            f"{pid}: fairkalah_value {actual} != expected {expected}"


def test_standard_best_moves(ref_data):
    positions, results, refs = ref_data
    for pos in positions:
        pid = pos["id"]
        state = refs[pid]["state"]
        move = results["positions"][pid]["standard_best_move"]
        assert move in state.legal_moves(), \
            f"{pid}: standard_best_move {move} not legal"
        child = state.clone()
        child.make_move(move, captures=True)
        val, _ = _ref_minimax(child, True, refs[pid]["std_tt"])
        assert val == refs[pid]["std_val"], \
            f"{pid}: standard_best_move {move} yields {val}, expected {refs[pid]['std_val']}"


def test_fairkalah_best_moves(ref_data):
    positions, results, refs = ref_data
    for pos in positions:
        pid = pos["id"]
        state = refs[pid]["state"]
        move = results["positions"][pid]["fairkalah_best_move"]
        assert move in state.legal_moves(), \
            f"{pid}: fairkalah_best_move {move} not legal"
        child = state.clone()
        child.make_move(move, captures=False)
        val, _ = _ref_minimax(child, False, refs[pid]["fair_tt"])
        assert val == refs[pid]["fair_val"], \
            f"{pid}: fairkalah_best_move {move} yields {val}, expected {refs[pid]['fair_val']}"


def test_pie_rule_values(ref_data):
    positions, results, refs = ref_data
    for pos in positions:
        pid = pos["id"]
        r = results["positions"][pid]

        if pos["side_to_move"] != "south":
            assert r["pie_rule_value"] is None, \
                f"{pid}: pie_rule_value should be null"
            assert r["pie_rule_first_moves"] is None, \
                f"{pid}: pie_rule_first_moves should be null"
            continue

        expected_pie = refs[pid]["pie_val"]
        assert r["pie_rule_value"] == expected_pie, \
            f"{pid}: pie_rule_value {r['pie_rule_value']} != {expected_pie}"

        seq = r["pie_rule_first_moves"]
        assert seq is not None and len(seq) > 0, \
            f"{pid}: pie_rule_first_moves must be non-empty list"

        state = refs[pid]["state"]
        s = state.clone()
        for i, mv in enumerate(seq):
            assert mv in s.legal_moves(), \
                f"{pid}: invalid move {mv} at step {i}"
            extra = s.make_move(mv, captures=False)
            if i < len(seq) - 1:
                assert extra, \
                    f"{pid}: move {mv} at step {i} must give extra turn"

        if s.is_terminal():
            val = s.terminal_score()
        else:
            val, _ = _ref_minimax(s, False, refs[pid]["fair_tt"])

        if val > 0:
            achieved = -val
        elif val < 0:
            achieved = val
        else:
            achieved = 0

        assert achieved == expected_pie, \
            f"{pid}: first-move sequence achieves pie value {achieved}, expected {expected_pie}"


# ---------------------------------------------------------------------------
# Tests: Endgame database
# ---------------------------------------------------------------------------

def test_endgame_db_exists():
    assert os.path.exists("/app/endgame.db"), "/app/endgame.db not found"


def test_endgame_db_schema():
    conn = sqlite3.connect("/app/endgame.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    assert "endgame_positions" in tables, "Missing endgame_positions table"
    conn.close()


def test_endgame_db_entry_counts():
    conn = sqlite3.connect("/app/endgame.db")
    cursor = conn.cursor()

    for seeds in [1, 2]:
        n = 3
        total_stones = 2 * n * seeds
        num_pos = 2 * (n + 1)
        expected_dists = _expected_distributions(total_stones, num_pos)
        expected_entries = expected_dists * 2  # both sides

        for captures_val in [0, 1]:
            variant = "standard" if captures_val == 1 else "fairkalah"
            cursor.execute(
                "SELECT COUNT(*) FROM endgame_positions "
                "WHERE n=? AND total_stones=? AND captures=?",
                (n, total_stones, captures_val)
            )
            actual = cursor.fetchone()[0]
            assert actual == expected_entries, (
                f"Kalah({n},{seeds}) {variant}: "
                f"DB has {actual} entries, expected {expected_entries}"
            )

    conn.close()


def test_endgame_db_spot_check(ref_data):
    """Spot-check specific entries in the endgame database."""
    positions, results, refs = ref_data
    conn = sqlite3.connect("/app/endgame.db")
    cursor = conn.cursor()

    # Check Kalah(3,1) initial position under both rules
    board_key_31 = "1,1,1,0,1,1,1,0"
    for captures_val, ref_key in [(1, "std_val"), (0, "fair_val")]:
        cursor.execute(
            "SELECT value FROM endgame_positions "
            "WHERE board_key=? AND side=0 AND captures=?",
            (board_key_31, captures_val)
        )
        row = cursor.fetchone()
        assert row is not None, \
            f"Missing DB entry for Kalah(3,1) initial, captures={captures_val}"
        assert row[0] == refs["pos1"][ref_key], \
            f"DB value {row[0]} != ref {refs['pos1'][ref_key]} for Kalah(3,1) initial captures={captures_val}"

    # Check Kalah(3,2) initial position under both rules
    board_key_32 = "2,2,2,0,2,2,2,0"
    for captures_val, ref_key in [(1, "std_val"), (0, "fair_val")]:
        cursor.execute(
            "SELECT value FROM endgame_positions "
            "WHERE board_key=? AND side=0 AND captures=?",
            (board_key_32, captures_val)
        )
        row = cursor.fetchone()
        assert row is not None, \
            f"Missing DB entry for Kalah(3,2) initial, captures={captures_val}"
        assert row[0] == refs["pos2"][ref_key], \
            f"DB value {row[0]} != ref {refs['pos2'][ref_key]} for Kalah(3,2) initial captures={captures_val}"

    conn.close()


# ---------------------------------------------------------------------------
# Tests: Balance statistics
# ---------------------------------------------------------------------------

def test_balance_stats(ref_data, ref_balance):
    _, results, _ = ref_data

    assert "balance" in results, "Missing 'balance' key in results"

    for key, expected in ref_balance.items():
        assert key in results["balance"], f"Missing balance entry for '{key}'"
        actual = results["balance"][key]

        assert actual["total_positions"] == expected["total_positions"], (
            f"{key}: total_positions {actual['total_positions']} "
            f"!= expected {expected['total_positions']}"
        )
        assert abs(actual["south_win_frac"] - expected["south_win_frac"]) < 1e-5, (
            f"{key}: south_win_frac {actual['south_win_frac']} "
            f"!= expected {expected['south_win_frac']}"
        )
        assert abs(actual["draw_frac"] - expected["draw_frac"]) < 1e-5, (
            f"{key}: draw_frac {actual['draw_frac']} "
            f"!= expected {expected['draw_frac']}"
        )
        assert abs(actual["north_win_frac"] - expected["north_win_frac"]) < 1e-5, (
            f"{key}: north_win_frac {actual['north_win_frac']} "
            f"!= expected {expected['north_win_frac']}"
        )


def test_balance_expected_keys(ref_data):
    _, results, _ = ref_data
    expected_keys = ["3_1_standard", "3_1_fairkalah", "3_2_standard", "3_2_fairkalah"]
    for key in expected_keys:
        assert key in results.get("balance", {}), \
            f"Missing balance key '{key}'"
