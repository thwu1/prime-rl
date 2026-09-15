"""Tests for Mancala variant solver, endgame database, and analysis."""

import json
import os
import sqlite3
import subprocess
import sys

import pytest

sys.path.insert(0, "/tests")
import reference


# Hardcoded task specification — independent of /app/positions.json
SOLVE_INITIAL = [
    [2, 2], [2, 3], [3, 2], [3, 3], [4, 2], [4, 3],
]

EVALUATE = [
    {"h": 3, "board": [0, 2, 1, 7, 1, 3, 0, 4], "side": 0},
    {"h": 3, "board": [1, 0, 3, 5, 0, 4, 1, 4], "side": 1},
    {"h": 3, "board": [3, 0, 0, 6, 0, 2, 1, 6], "side": 0},
    {"h": 3, "board": [0, 0, 0, 10, 3, 2, 3, 0], "side": 0},
    {"h": 3, "board": [2, 1, 0, 8, 0, 3, 1, 3], "side": 1},
]

SWEEP_CONFIGS = [(h, s) for h in [2, 3, 4] for s in [1, 2, 3]]


def load_results():
    with open("/app/results.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Structural checks on results.json
# ---------------------------------------------------------------------------

class TestResultsFormat:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "/app/results.json not found"

    def test_results_has_initial(self):
        r = load_results()
        assert "initial" in r, "Missing 'initial' key"
        assert isinstance(r["initial"], dict)

    def test_results_has_positions(self):
        r = load_results()
        assert "positions" in r, "Missing 'positions' key"
        assert isinstance(r["positions"], list)

    def test_initial_keys_present(self):
        r = load_results()
        for h, s in SOLVE_INITIAL:
            key = f"{h}_{s}"
            assert key in r["initial"], f"Missing key '{key}'"

    def test_position_count(self):
        r = load_results()
        assert len(r["positions"]) == len(EVALUATE), (
            f"Expected {len(EVALUATE)} values, got {len(r['positions'])}"
        )


# ---------------------------------------------------------------------------
# Verify game-theoretic values for initial positions
# ---------------------------------------------------------------------------

class TestInitialValues:
    @pytest.mark.parametrize("h,s", SOLVE_INITIAL)
    def test_initial(self, h, s):
        r = load_results()
        expected = reference.solve_initial(h, s)
        actual = r["initial"][f"{h}_{s}"]
        assert actual == expected, (
            f"Variant({h},{s}): expected {expected}, got {actual}"
        )


# ---------------------------------------------------------------------------
# Verify mid-game position values
# ---------------------------------------------------------------------------

class TestPositionValues:
    @pytest.mark.parametrize("idx", range(5))
    def test_position(self, idx):
        r = load_results()
        pos = EVALUATE[idx]
        h = pos["h"]
        board = tuple(pos["board"])
        side = pos["side"]
        expected = reference.solve(board, side, h)
        actual = r["positions"][idx]
        assert actual == expected, (
            f"Position {idx}: expected {expected}, got {actual}"
        )


# ---------------------------------------------------------------------------
# Verify the CLI solver on positions NOT in positions.json
# ---------------------------------------------------------------------------

class TestSolverCLI:
    def _call_solver(self, h, board, side):
        board_csv = ",".join(map(str, board))
        result = subprocess.run(
            ["python3", "/app/solve.py", str(h), board_csv, str(side)],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, (
            f"solve.py exited with code {result.returncode}\n"
            f"stderr: {result.stderr[:500]}"
        )
        return int(result.stdout.strip())

    def test_solve_py_exists(self):
        assert os.path.exists("/app/solve.py"), "/app/solve.py not found"

    def test_game_over_south_empty(self):
        board = (0, 0, 0, 12, 2, 2, 2, 0)
        expected = reference.solve(board, 0, 3)
        assert self._call_solver(3, board, 0) == expected

    def test_game_over_north_empty(self):
        board = (2, 2, 2, 0, 0, 0, 0, 12)
        expected = reference.solve(board, 1, 3)
        assert self._call_solver(3, board, 1) == expected

    def test_extra_turn_into_store(self):
        board = (0, 0, 3, 6, 1, 2, 0, 6)
        expected = reference.solve(board, 0, 3)
        assert self._call_solver(3, board, 0) == expected

    def test_single_seed_position(self):
        board = (0, 1, 0, 8, 0, 0, 1, 6)
        expected = reference.solve(board, 0, 3)
        assert self._call_solver(3, board, 0) == expected

    def test_large_pit_wrapping(self):
        board = (10, 0, 0, 2, 0, 0, 0, 6)
        expected = reference.solve(board, 0, 3)
        assert self._call_solver(3, board, 0) == expected

    def test_north_to_move(self):
        board = (0, 3, 1, 4, 2, 0, 2, 6)
        expected = reference.solve(board, 1, 3)
        assert self._call_solver(3, board, 1) == expected

    def test_relay_trigger_position(self):
        board = (1, 3, 0, 5, 1, 1, 1, 6)
        expected = reference.solve(board, 0, 3)
        assert self._call_solver(3, board, 0) == expected

    def test_positions_from_small_game(self):
        positions = self._play_deterministic_game(2, 2)
        for board, side in positions:
            expected = reference.solve(board, side, 2)
            actual = self._call_solver(2, board, side)
            assert actual == expected

    def test_positions_from_medium_game(self):
        positions = self._play_deterministic_game(2, 3)
        for board, side in positions[:12]:
            expected = reference.solve(board, side, 2)
            actual = self._call_solver(2, board, side)
            assert actual == expected

    @staticmethod
    def _play_deterministic_game(h, s):
        board = tuple([s] * h + [0] + [s] * h + [0])
        side = 0
        positions = []
        for _ in range(300):
            moves = reference.get_moves(board, side, h)
            if not moves:
                break
            positions.append((board, side))
            board, side = reference.make_move(board, side, moves[0], h)
            if side == -1:
                break
        return positions


# ---------------------------------------------------------------------------
# Verify endgame database
# ---------------------------------------------------------------------------

class TestEndgameDB:
    def test_db_exists(self):
        assert os.path.exists("/app/endgame.db"), "/app/endgame.db not found"

    def test_db_table_schema(self):
        conn = sqlite3.connect("/app/endgame.db")
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='endgame'"
        )
        assert cur.fetchone() is not None, "Table 'endgame' not found"
        cur = conn.execute("PRAGMA table_info(endgame)")
        cols = {row[1] for row in cur.fetchall()}
        for c in ("board", "side", "value", "best_move"):
            assert c in cols, f"Column '{c}' missing"
        conn.close()

    def test_db_initial_position(self):
        conn = sqlite3.connect("/app/endgame.db")
        cur = conn.execute(
            "SELECT value, best_move FROM endgame WHERE board=? AND side=?",
            ("3,3,3,0,3,3,3,0", 0),
        )
        row = cur.fetchone()
        assert row is not None, "Initial (3,3) position missing from database"
        expected = reference.solve_initial(3, 3)
        assert row[0] == expected, (
            f"Initial value: expected {expected}, got {row[0]}"
        )
        assert row[1] is not None, "Initial position must have a best_move"
        conn.close()

    def test_db_row_count(self):
        conn = sqlite3.connect("/app/endgame.db")
        cur = conn.execute("SELECT COUNT(*) FROM endgame")
        count = cur.fetchone()[0]
        expected = reference.count_reachable(3, 3)
        assert count == expected, (
            f"Expected {expected} rows, got {count}"
        )
        conn.close()

    def test_db_sample_values(self):
        """Spot-check entries from different parts of the database."""
        conn = sqlite3.connect("/app/endgame.db")
        total = conn.execute("SELECT COUNT(*) FROM endgame").fetchone()[0]
        shared_memo = {}
        checked = 0
        for offset in [0, total // 4, total // 2, 3 * total // 4]:
            cur = conn.execute(
                "SELECT board, side, value FROM endgame "
                "ORDER BY board, side LIMIT 10 OFFSET ?",
                (offset,),
            )
            for board_str, side, value in cur:
                board = tuple(map(int, board_str.split(",")))
                expected = reference.solve(board, side, 3, memo=shared_memo)
                assert value == expected, (
                    f"DB entry board={board_str} side={side}: "
                    f"expected {expected}, got {value}"
                )
                checked += 1
        assert checked >= 20, f"Only checked {checked} entries"
        conn.close()

    def test_db_best_moves_legal(self):
        """Verify best_move values are legal moves."""
        conn = sqlite3.connect("/app/endgame.db")
        cur = conn.execute(
            "SELECT board, side, best_move FROM endgame "
            "WHERE best_move IS NOT NULL "
            "ORDER BY board LIMIT 40"
        )
        for board_str, side, best_move in cur:
            board = tuple(map(int, board_str.split(",")))
            moves = reference.get_moves(board, side, 3)
            assert best_move in moves, (
                f"best_move {best_move} not legal for "
                f"board={board_str}, side={side}"
            )
        conn.close()


# ---------------------------------------------------------------------------
# Verify analysis.json
# ---------------------------------------------------------------------------

class TestAnalysis:
    def test_analysis_exists(self):
        assert os.path.exists("/app/analysis.json")

    def test_sweep_values(self):
        with open("/app/analysis.json") as f:
            a = json.load(f)
        assert "sweep" in a
        for h, s in SWEEP_CONFIGS:
            key = f"{h}_{s}"
            assert key in a["sweep"], f"Missing sweep key {key}"
            expected = reference.solve_initial(h, s)
            assert a["sweep"][key] == expected, (
                f"Sweep({h},{s}): expected {expected}, got {a['sweep'][key]}"
            )

    def test_reachable_count(self):
        with open("/app/analysis.json") as f:
            a = json.load(f)
        assert "reachable_3_3" in a
        expected = reference.count_reachable(3, 3)
        assert a["reachable_3_3"] == expected, (
            f"Expected {expected}, got {a['reachable_3_3']}"
        )

    def test_pv_exists_and_nonempty(self):
        with open("/app/analysis.json") as f:
            a = json.load(f)
        assert "principal_variation_3_2" in a
        assert len(a["principal_variation_3_2"]) > 0

    def test_pv_moves_valid(self):
        """Each PV move must be legal and produce the stated board."""
        with open("/app/analysis.json") as f:
            a = json.load(f)
        pv = a["principal_variation_3_2"]
        board = tuple([2] * 3 + [0] + [2] * 3 + [0])
        side = 0
        h = 3
        for i, step in enumerate(pv):
            assert step["side"] == side, f"PV step {i}: expected side {side}"
            pit = step["pit"]
            moves = reference.get_moves(board, side, h)
            assert pit in moves, f"PV step {i}: pit {pit} not legal"
            nb, ns = reference.make_move(board, side, pit, h)
            assert step["board_after"] == list(nb), (
                f"PV step {i}: board mismatch"
            )
            if ns == -1:
                assert i == len(pv) - 1, "PV continues after game over"
                break
            board, side = nb, ns

    def test_pv_optimal(self):
        """Each PV move must achieve the game-theoretic value."""
        with open("/app/analysis.json") as f:
            a = json.load(f)
        pv = a["principal_variation_3_2"]
        board = tuple([2] * 3 + [0] + [2] * 3 + [0])
        side = 0
        h = 3
        shared_memo = {}
        for step in pv:
            gt_val = reference.solve(board, side, h, memo=shared_memo)
            pit = step["pit"]
            nb, ns = reference.make_move(board, side, pit, h)
            if ns == -1:
                move_val = nb[h] - nb[2 * h + 1]
            else:
                move_val = reference.solve(nb, ns, h, memo=shared_memo)
            assert move_val == gt_val, (
                f"PV pit={pit}: value {move_val} vs optimal {gt_val}"
            )
            if ns == -1:
                break
            board, side = nb, ns
