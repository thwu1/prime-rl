
"""
Tests for the Kalah multi-variant analysis engine.
Verifies game values, principal variations, pie-rule analysis,
SQLite database output, shared library, validation report,
and gnuplot visualization against an independent reference solver.
"""

import json
import os
import sys
import sqlite3
import ctypes
import subprocess
import pytest

sys.setrecursionlimit(2_000_000)

RESULTS_PATH = "/app/results.json"
PROBLEMS_PATH = "/app/problems.json"
DB_PATH = "/app/analysis.db"
LIB_PATH = "/app/libkalah.so"
VALIDATION_PATH = "/app/validation_report.json"
SVG_PATH = "/app/game_analysis.svg"


# ──────────────────────────────────────────────────────────────
# Reference solver
# ──────────────────────────────────────────────────────────────

def _ref_solve(n, k, captures, misere, board=None, player=0):
    """
    Independent Kalah minimax solver with memoization.
    Returns (value, {local_pit_str: value}).
    """
    bsz = 2 * n + 2
    ss = n
    ns = 2 * n + 1

    if board is None:
        board = tuple([k] * n + [0] + [k] * n + [0])

    cache = {}

    def moves(b, p):
        if p == 0:
            return [i for i in range(n) if b[i] > 0]
        return [i for i in range(n + 1, 2 * n + 1) if b[i] > 0]

    def do_move(b, p, pit):
        bl = list(b)
        sd = bl[pit]
        bl[pit] = 0
        skip = ns if p == 0 else ss
        c = pit
        while sd:
            c = (c + 1) % bsz
            if c == skip:
                continue
            bl[c] += 1
            sd -= 1
        my_s = ss if p == 0 else ns
        extra = (c == my_s)
        if captures and not extra:
            if p == 0 and 0 <= c < n and bl[c] == 1:
                o = 2 * n - c
                if bl[o] > 0:
                    bl[ss] += 1 + bl[o]
                    bl[c] = 0
                    bl[o] = 0
            elif p == 1 and n + 1 <= c <= 2 * n and bl[c] == 1:
                o = 2 * n - c
                if bl[o] > 0:
                    bl[ns] += 1 + bl[o]
                    bl[c] = 0
                    bl[o] = 0
        se = all(bl[i] == 0 for i in range(n))
        ne = all(bl[i] == 0 for i in range(n + 1, 2 * n + 1))
        if se or ne:
            for i in range(n):
                bl[ss] += bl[i]; bl[i] = 0
            for i in range(n + 1, 2 * n + 1):
                bl[ns] += bl[i]; bl[i] = 0
            return tuple(bl), -1, True
        return tuple(bl), p if extra else 1 - p, False

    def minimax(b, p):
        key = (b, p)
        if key in cache:
            return cache[key]
        ms = moves(b, p)
        if not ms:
            bl = list(b)
            for i in range(n):
                bl[ss] += bl[i]; bl[i] = 0
            for i in range(n + 1, 2 * n + 1):
                bl[ns] += bl[i]; bl[i] = 0
            v = bl[ss] - bl[ns]
            cache[key] = v
            return v
        vals = []
        for m in ms:
            nb, np_v, go = do_move(b, p, m)
            if go:
                vals.append(nb[ss] - nb[ns])
            else:
                vals.append(minimax(nb, np_v))
        if misere:
            v = min(vals) if p == 0 else max(vals)
        else:
            v = max(vals) if p == 0 else min(vals)
        cache[key] = v
        return v

    value = minimax(board, player)

    ms = moves(board, player)
    mv = {}
    for m in ms:
        nb, np_v, go = do_move(board, player, m)
        if go:
            mv_val = nb[ss] - nb[ns]
        else:
            mv_val = minimax(nb, np_v)
        local = m if player == 0 else m - (n + 1)
        mv[str(local)] = mv_val

    return value, mv


# ──────────────────────────────────────────────────────────────
# PV replay validator
# ──────────────────────────────────────────────────────────────

def _replay_pv(pv, n, k, captures, board=None, player=0):
    """
    Replay a principal variation from a starting position.
    Returns (final_value, game_over, error_message_or_None).
    """
    bsz = 2 * n + 2
    ss = n
    ns = 2 * n + 1

    if board is None:
        b = [k] * n + [0] + [k] * n + [0]
    else:
        b = list(board)

    p = player
    game_ended = False

    for idx, step in enumerate(pv):
        expected_player = "south" if p == 0 else "north"
        if step["player"] != expected_player:
            return None, False, (
                f"Step {idx}: expected player {expected_player}, "
                f"got {step['player']}"
            )

        local_pit = step["pit"]
        if p == 0:
            pit = local_pit
            if pit < 0 or pit >= n:
                return None, False, f"Step {idx}: south pit {pit} out of range"
            if b[pit] == 0:
                return None, False, f"Step {idx}: south pit {pit} is empty"
        else:
            pit = n + 1 + local_pit
            if local_pit < 0 or local_pit >= n:
                return None, False, f"Step {idx}: north pit {local_pit} out of range"
            if b[pit] == 0:
                return None, False, f"Step {idx}: north pit {local_pit} is empty"

        seeds = b[pit]
        b[pit] = 0
        skip = ns if p == 0 else ss
        c = pit
        while seeds:
            c = (c + 1) % bsz
            if c == skip:
                continue
            b[c] += 1
            seeds -= 1

        my_store = ss if p == 0 else ns
        extra = (c == my_store)

        if captures and not extra:
            if p == 0 and 0 <= c < n and b[c] == 1:
                o = 2 * n - c
                if b[o] > 0:
                    b[ss] += 1 + b[o]
                    b[c] = 0
                    b[o] = 0
            elif p == 1 and n + 1 <= c <= 2 * n and b[c] == 1:
                o = 2 * n - c
                if b[o] > 0:
                    b[ns] += 1 + b[o]
                    b[c] = 0
                    b[o] = 0

        se = all(b[i] == 0 for i in range(n))
        ne = all(b[i] == 0 for i in range(n + 1, 2 * n + 1))
        if se or ne:
            for i in range(n):
                b[ss] += b[i]; b[i] = 0
            for i in range(n + 1, 2 * n + 1):
                b[ns] += b[i]; b[i] = 0
            game_ended = True
            break

        if not extra:
            p = 1 - p

    if not game_ended:
        se = all(b[i] == 0 for i in range(n))
        ne = all(b[i] == 0 for i in range(n + 1, 2 * n + 1))
        if se or ne:
            for i in range(n):
                b[ss] += b[i]; b[i] = 0
            for i in range(n + 1, 2 * n + 1):
                b[ns] += b[i]; b[i] = 0
            game_ended = True

    return b[ss] - b[ns], game_ended, None


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _load_results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


def _load_problems():
    with open(PROBLEMS_PATH) as f:
        return json.load(f)


def _get_problem_params(prob):
    n = prob["pits_per_side"]
    k = prob["seeds_per_pit"]
    captures = prob["capture_rule"] == "standard"
    misere = prob["objective"] == "misere"
    pie_rule = prob.get("pie_rule", False)
    if prob["starting_position"] == "initial":
        board = None
        player = 0
    else:
        sp = prob["starting_position"]
        board = tuple(
            sp["south_pits"] + [sp["south_store"]]
            + sp["north_pits"] + [sp["north_store"]]
        )
        player = 0 if sp["side_to_move"] == "south" else 1
    return n, k, captures, misere, pie_rule, board, player


def _check_problem_values(pid, problems, results):
    """Verify game value and move values for one problem."""
    prob = problems[pid]
    res = results[pid]
    n, k, captures, misere, pie_rule, board, player = _get_problem_params(prob)
    ref_value, ref_mv = _ref_solve(n, k, captures, misere, board, player)

    assert res["game_theoretic_value"] == ref_value, (
        f"{pid}: game_theoretic_value {res['game_theoretic_value']} "
        f"!= expected {ref_value}"
    )

    for move_str, val in ref_mv.items():
        assert move_str in res["all_move_values"], (
            f"{pid}: missing move {move_str} in all_move_values"
        )
        assert res["all_move_values"][move_str] == val, (
            f"{pid}: move {move_str} value "
            f"{res['all_move_values'][move_str]} != expected {val}"
        )
    assert len(res["all_move_values"]) == len(ref_mv), (
        f"{pid}: extra moves in all_move_values"
    )

    opt = str(res["optimal_first_move"])
    assert opt in res["all_move_values"], (
        f"{pid}: optimal_first_move {opt} not in all_move_values"
    )
    opt_val = res["all_move_values"][opt]
    if misere:
        expected_opt = (min(res["all_move_values"].values()) if player == 0
                        else max(res["all_move_values"].values()))
    else:
        expected_opt = (max(res["all_move_values"].values()) if player == 0
                        else min(res["all_move_values"].values()))
    assert opt_val == expected_opt, (
        f"{pid}: optimal move value {opt_val} != best available {expected_opt}"
    )


def _check_pv(pid, problems, results):
    """Verify principal variation for one problem."""
    prob = problems[pid]
    res = results[pid]
    n, k, captures, misere, pie_rule, board, player = _get_problem_params(prob)

    pv = res["principal_variation"]
    assert isinstance(pv, list), f"{pid}: principal_variation is not a list"
    assert len(pv) > 0, f"{pid}: principal_variation is empty"

    for i, step in enumerate(pv):
        assert "player" in step and "pit" in step, (
            f"{pid}: PV step {i} missing player or pit"
        )
        assert step["player"] in ("south", "north"), (
            f"{pid}: PV step {i} invalid player {step['player']}"
        )
        assert isinstance(step["pit"], int), (
            f"{pid}: PV step {i} pit is not int"
        )

    board_list = list(board) if board else None
    final_val, game_ended, err = _replay_pv(
        pv, n, k, captures, board_list, player
    )

    assert err is None, f"{pid}: PV replay error: {err}"
    assert game_ended, f"{pid}: PV does not reach terminal position"
    assert final_val == res["game_theoretic_value"], (
        f"{pid}: PV final value {final_val} != "
        f"game_theoretic_value {res['game_theoretic_value']}"
    )

    # Verify first move is optimal
    first_pit = str(pv[0]["pit"])
    assert first_pit in res["all_move_values"], (
        f"{pid}: PV first move pit {first_pit} not in all_move_values"
    )
    assert res["all_move_values"][first_pit] == res["game_theoretic_value"], (
        f"{pid}: PV first move value "
        f"{res['all_move_values'][first_pit]} != "
        f"game_theoretic_value {res['game_theoretic_value']}"
    )


# ──────────────────────────────────────────────────────────────
# Tests: File existence and format
# ──────────────────────────────────────────────────────────────

class TestResultsExist:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH), f"{RESULTS_PATH} not found"

    def test_results_valid_json(self):
        data = _load_results()
        assert "results" in data, "results key missing"
        assert isinstance(data["results"], list), "results is not a list"

    def test_all_problems_present(self):
        data = _load_results()
        probs = _load_problems()
        result_ids = {r["id"] for r in data["results"]}
        for p in probs["problems"]:
            assert p["id"] in result_ids, f"Missing result for {p['id']}"


class TestResultsFormat:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = _load_results()
        self.results = {r["id"]: r for r in self.data["results"]}
        self.probs_data = _load_problems()
        self.problems = {p["id"]: p for p in self.probs_data["problems"]}

    def test_required_fields(self):
        for pid, r in self.results.items():
            for field in ("game_theoretic_value", "optimal_first_move",
                          "all_move_values", "principal_variation"):
                assert field in r, f"{pid}: missing {field}"

    def test_field_types(self):
        for pid, r in self.results.items():
            assert isinstance(r["game_theoretic_value"], int), (
                f"{pid}: game_theoretic_value not int"
            )
            assert isinstance(r["optimal_first_move"], int), (
                f"{pid}: optimal_first_move not int"
            )
            assert isinstance(r["all_move_values"], dict), (
                f"{pid}: all_move_values not dict"
            )
            assert isinstance(r["principal_variation"], list), (
                f"{pid}: principal_variation not list"
            )

    def test_pie_rule_fields_present(self):
        for pid, prob in self.problems.items():
            if prob.get("pie_rule", False):
                r = self.results[pid]
                assert "pie_rule_value" in r, (
                    f"{pid}: missing pie_rule_value"
                )
                assert "pie_rule_optimal_opening" in r, (
                    f"{pid}: missing pie_rule_optimal_opening"
                )
                assert isinstance(r["pie_rule_value"], int), (
                    f"{pid}: pie_rule_value not int"
                )
                assert isinstance(r["pie_rule_optimal_opening"], int), (
                    f"{pid}: pie_rule_optimal_opening not int"
                )


# ──────────────────────────────────────────────────────────────
# Tests: Seed conservation
# ──────────────────────────────────────────────────────────────

class TestSeedConservation:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = _load_results()
        self.results = {r["id"]: r for r in self.data["results"]}
        self.probs_data = _load_problems()
        self.problems = {p["id"]: p for p in self.probs_data["problems"]}

    def test_value_parity(self):
        for pid, prob in self.problems.items():
            r = self.results[pid]
            n = prob["pits_per_side"]
            k = prob["seeds_per_pit"]
            if prob["starting_position"] == "initial":
                total = 2 * n * k
            else:
                sp = prob["starting_position"]
                total = (sum(sp["south_pits"]) + sp["south_store"]
                         + sum(sp["north_pits"]) + sp["north_store"])
            v = r["game_theoretic_value"]
            assert (total + v) % 2 == 0, (
                f"{pid}: value {v} incompatible with total seeds {total}"
            )
            south = (total + v) // 2
            north = (total - v) // 2
            assert 0 <= south <= total, (
                f"{pid}: implied south score {south} out of range"
            )
            assert 0 <= north <= total, (
                f"{pid}: implied north score {north} out of range"
            )


# ──────────────────────────────────────────────────────────────
# Tests: Game value correctness
# ──────────────────────────────────────────────────────────────

class TestGameValues:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = _load_results()
        self.results = {r["id"]: r for r in self.data["results"]}
        self.probs_data = _load_problems()
        self.problems = {p["id"]: p for p in self.probs_data["problems"]}

    def test_P1_kalah33_standard_normal(self):
        _check_problem_values("P1", self.problems, self.results)

    def test_P2_kalah33_nocapture_normal(self):
        _check_problem_values("P2", self.problems, self.results)

    def test_P3_kalah42_standard_normal(self):
        _check_problem_values("P3", self.problems, self.results)

    def test_P4_kalah33_standard_misere(self):
        _check_problem_values("P4", self.problems, self.results)

    def test_P5_kalah33_nocapture_misere(self):
        _check_problem_values("P5", self.problems, self.results)

    def test_P6_kalah33_midgame_north(self):
        _check_problem_values("P6", self.problems, self.results)

    def test_P7_kalah42_midgame_south(self):
        _check_problem_values("P7", self.problems, self.results)

    def test_P8_kalah33_standard_normal_values(self):
        _check_problem_values("P8", self.problems, self.results)

    def test_P9_kalah42_standard_normal_values(self):
        _check_problem_values("P9", self.problems, self.results)


# ──────────────────────────────────────────────────────────────
# Tests: Principal variation validity
# ──────────────────────────────────────────────────────────────

class TestPrincipalVariation:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = _load_results()
        self.results = {r["id"]: r for r in self.data["results"]}
        self.probs_data = _load_problems()
        self.problems = {p["id"]: p for p in self.probs_data["problems"]}

    def test_pv_P1(self):
        _check_pv("P1", self.problems, self.results)

    def test_pv_P2(self):
        _check_pv("P2", self.problems, self.results)

    def test_pv_P3(self):
        _check_pv("P3", self.problems, self.results)

    def test_pv_P4(self):
        _check_pv("P4", self.problems, self.results)

    def test_pv_P5(self):
        _check_pv("P5", self.problems, self.results)

    def test_pv_P6(self):
        _check_pv("P6", self.problems, self.results)

    def test_pv_P7(self):
        _check_pv("P7", self.problems, self.results)

    def test_pv_P8(self):
        _check_pv("P8", self.problems, self.results)

    def test_pv_P9(self):
        _check_pv("P9", self.problems, self.results)


# ──────────────────────────────────────────────────────────────
# Tests: Pie rule
# ──────────────────────────────────────────────────────────────

class TestPieRule:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = _load_results()
        self.results = {r["id"]: r for r in self.data["results"]}
        self.probs_data = _load_problems()
        self.problems = {p["id"]: p for p in self.probs_data["problems"]}

    def _check_pie(self, pid):
        prob = self.problems[pid]
        res = self.results[pid]
        n, k, captures, misere, pie_rule, board, player = \
            _get_problem_params(prob)
        assert pie_rule, f"{pid} is not a pie-rule problem"

        ref_value, ref_mv = _ref_solve(
            n, k, captures, misere, board, player
        )

        abs_vals = {m: abs(v) for m, v in ref_mv.items()}
        min_abs = min(abs_vals.values())
        expected_pie_value = -min_abs
        expected_pie_opening = min(
            int(m) for m, v in abs_vals.items() if v == min_abs
        )

        assert res["pie_rule_value"] == expected_pie_value, (
            f"{pid}: pie_rule_value {res['pie_rule_value']} "
            f"!= expected {expected_pie_value}"
        )
        assert res["pie_rule_optimal_opening"] == expected_pie_opening, (
            f"{pid}: pie_rule_optimal_opening "
            f"{res['pie_rule_optimal_opening']} "
            f"!= expected {expected_pie_opening}"
        )

    def test_P8_pie_rule(self):
        self._check_pie("P8")

    def test_P9_pie_rule(self):
        self._check_pie("P9")


# ──────────────────────────────────────────────────────────────
# Tests: SQLite database — schema and data
# ──────────────────────────────────────────────────────────────

class TestSQLiteExists:
    def test_db_file_exists(self):
        assert os.path.exists(DB_PATH), f"{DB_PATH} not found"

    def test_has_solutions_table(self):
        db = sqlite3.connect(DB_PATH)
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='solutions'"
        )
        assert cur.fetchone() is not None, "solutions table missing"
        db.close()

    def test_has_move_values_table(self):
        db = sqlite3.connect(DB_PATH)
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='move_values'"
        )
        assert cur.fetchone() is not None, "move_values table missing"
        db.close()

    def test_has_pv_table(self):
        db = sqlite3.connect(DB_PATH)
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='principal_variations'"
        )
        assert cur.fetchone() is not None, "principal_variations table missing"
        db.close()

    def test_solutions_columns(self):
        db = sqlite3.connect(DB_PATH)
        cur = db.execute("PRAGMA table_info(solutions)")
        cols = {row[1] for row in cur.fetchall()}
        expected = {"problem_id", "game_theoretic_value",
                    "optimal_first_move", "pv_length",
                    "pie_rule_value", "pie_rule_optimal_opening"}
        for c in expected:
            assert c in cols, f"solutions table missing column {c}"
        db.close()

    def test_move_values_columns(self):
        db = sqlite3.connect(DB_PATH)
        cur = db.execute("PRAGMA table_info(move_values)")
        cols = {row[1] for row in cur.fetchall()}
        for c in ("problem_id", "move_index", "value"):
            assert c in cols, f"move_values table missing column {c}"
        db.close()

    def test_pv_columns(self):
        db = sqlite3.connect(DB_PATH)
        cur = db.execute("PRAGMA table_info(principal_variations)")
        cols = {row[1] for row in cur.fetchall()}
        for c in ("problem_id", "step", "player", "pit"):
            assert c in cols, (
                f"principal_variations table missing column {c}"
            )
        db.close()


class TestSQLiteData:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.json_data = _load_results()
        self.json_results = {r["id"]: r for r in self.json_data["results"]}
        self.db = sqlite3.connect(DB_PATH)
        self.db.row_factory = sqlite3.Row

    def teardown_method(self):
        self.db.close()

    def test_solutions_count(self):
        cur = self.db.execute("SELECT COUNT(*) FROM solutions")
        count = cur.fetchone()[0]
        assert count == len(self.json_results), (
            f"solutions has {count} rows, expected {len(self.json_results)}"
        )

    def test_solutions_values_match(self):
        for pid, jr in self.json_results.items():
            cur = self.db.execute(
                "SELECT * FROM solutions WHERE problem_id = ?", (pid,)
            )
            row = cur.fetchone()
            assert row is not None, f"solutions missing {pid}"
            assert row["game_theoretic_value"] == jr["game_theoretic_value"]
            assert row["optimal_first_move"] == jr["optimal_first_move"]
            assert row["pv_length"] == len(jr["principal_variation"])
            if "pie_rule_value" in jr:
                assert row["pie_rule_value"] == jr["pie_rule_value"]
                assert (row["pie_rule_optimal_opening"]
                        == jr["pie_rule_optimal_opening"])
            else:
                assert row["pie_rule_value"] is None

    def test_move_values_match(self):
        for pid, jr in self.json_results.items():
            cur = self.db.execute(
                "SELECT move_index, value FROM move_values "
                "WHERE problem_id = ? ORDER BY move_index", (pid,)
            )
            db_mv = {str(row["move_index"]): row["value"]
                     for row in cur.fetchall()}
            assert db_mv == jr["all_move_values"], (
                f"{pid}: move_values DB data != JSON"
            )

    def test_pv_match(self):
        for pid, jr in self.json_results.items():
            cur = self.db.execute(
                "SELECT step, player, pit FROM principal_variations "
                "WHERE problem_id = ? ORDER BY step", (pid,)
            )
            db_pv = [{"player": row["player"], "pit": row["pit"]}
                     for row in cur.fetchall()]
            assert len(db_pv) == len(jr["principal_variation"]), (
                f"{pid}: PV length mismatch DB vs JSON"
            )
            for i, (db_step, json_step) in enumerate(
                zip(db_pv, jr["principal_variation"])
            ):
                assert db_step["player"] == json_step["player"], (
                    f"{pid} PV step {i}: player mismatch"
                )
                assert db_step["pit"] == json_step["pit"], (
                    f"{pid} PV step {i}: pit mismatch"
                )


# ──────────────────────────────────────────────────────────────
# Tests: Shared library (libkalah.so)
# ──────────────────────────────────────────────────────────────

class TestSharedLibrary:
    def test_libkalah_exists(self):
        assert os.path.exists(LIB_PATH), f"{LIB_PATH} not found"

    def test_libkalah_loadable(self):
        try:
            lib = ctypes.CDLL(LIB_PATH)
            assert lib is not None
        except OSError as e:
            pytest.fail(f"Cannot load {LIB_PATH}: {e}")

    def test_kalah_init_exported(self):
        result = subprocess.run(
            ["nm", "-D", LIB_PATH],
            capture_output=True, text=True
        )
        assert "kalah_init" in result.stdout, (
            "kalah_init symbol not exported from libkalah.so"
        )

    def test_kalah_play_exported(self):
        result = subprocess.run(
            ["nm", "-D", LIB_PATH],
            capture_output=True, text=True
        )
        assert "kalah_play" in result.stdout, (
            "kalah_play symbol not exported from libkalah.so"
        )

    def test_kalah_get_score_exported(self):
        result = subprocess.run(
            ["nm", "-D", LIB_PATH],
            capture_output=True, text=True
        )
        assert "kalah_get_score" in result.stdout, (
            "kalah_get_score symbol not exported from libkalah.so"
        )

    def test_engine_basic_game(self):
        """Verify the shared library functions work correctly."""
        lib = ctypes.CDLL(LIB_PATH)
        lib.kalah_init.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
        lib.kalah_init.restype = None
        lib.kalah_play.argtypes = [ctypes.c_int]
        lib.kalah_play.restype = ctypes.c_int
        lib.kalah_get_score.argtypes = []
        lib.kalah_get_score.restype = ctypes.c_int

        lib.kalah_init(3, 3, 1)
        assert lib.kalah_get_score() == 0, "Initial score should be 0"

        ret = lib.kalah_play(2)
        assert ret >= 0, "Playing pit 2 on initial Kalah(3,3) should succeed"

        score = lib.kalah_get_score()
        assert isinstance(score, int), "get_score should return int"


# ──────────────────────────────────────────────────────────────
# Tests: Validation report
# ──────────────────────────────────────────────────────────────

class TestValidationReport:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.probs_data = _load_problems()
        self.problem_ids = {p["id"] for p in self.probs_data["problems"]}

    def test_report_exists(self):
        assert os.path.exists(VALIDATION_PATH), (
            f"{VALIDATION_PATH} not found"
        )

    def test_report_valid_json(self):
        with open(VALIDATION_PATH) as f:
            data = json.load(f)
        assert isinstance(data, list), "validation_report should be a list"

    def test_report_all_problems(self):
        with open(VALIDATION_PATH) as f:
            data = json.load(f)
        report_ids = {entry["problem_id"] for entry in data}
        for pid in self.problem_ids:
            assert pid in report_ids, (
                f"Problem {pid} missing from validation report"
            )

    def test_report_all_match(self):
        with open(VALIDATION_PATH) as f:
            data = json.load(f)
        for entry in data:
            pid = entry["problem_id"]
            assert entry["match"] is True, (
                f"{pid}: validation mismatch — engine={entry['engine_final_score']}"
                f" solver={entry['solver_final_score']}"
            )
            assert entry["moves_validated"] > 0, (
                f"{pid}: no moves were validated"
            )

    def test_report_scores_consistent(self):
        with open(VALIDATION_PATH) as f:
            report = json.load(f)
        results_data = _load_results()
        results = {r["id"]: r for r in results_data["results"]}
        for entry in report:
            pid = entry["problem_id"]
            if pid in results:
                assert entry["solver_final_score"] == results[pid]["game_theoretic_value"], (
                    f"{pid}: validation solver_final_score doesn't match results.json"
                )


# ──────────────────────────────────────────────────────────────
# Tests: SVG visualization
# ──────────────────────────────────────────────────────────────

class TestVisualization:
    def test_svg_exists(self):
        assert os.path.exists(SVG_PATH), f"{SVG_PATH} not found"

    def test_svg_valid_format(self):
        with open(SVG_PATH) as f:
            content = f.read()
        assert "<svg" in content, "SVG file missing <svg tag"
        assert "</svg>" in content, "SVG file missing closing </svg> tag"

    def test_svg_contains_problem_ids(self):
        probs = _load_problems()
        pids = [p["id"] for p in probs["problems"]]
        with open(SVG_PATH) as f:
            content = f.read()
        found = sum(1 for pid in pids if pid in content)
        assert found >= 3, (
            f"SVG contains only {found} problem IDs, expected at least 3"
        )


# ──────────────────────────────────────────────────────────────
# Tests: Tree statistics table
# ──────────────────────────────────────────────────────────────

class TestTreeStats:
    def test_tree_stats_table_exists(self):
        db = sqlite3.connect(DB_PATH)
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='tree_stats'"
        )
        assert cur.fetchone() is not None, "tree_stats table missing"
        db.close()

    def test_tree_stats_columns(self):
        db = sqlite3.connect(DB_PATH)
        cur = db.execute("PRAGMA table_info(tree_stats)")
        cols = {row[1] for row in cur.fetchall()}
        for c in ("problem_id", "nodes_evaluated", "unique_positions",
                   "max_depth", "branching_factor"):
            assert c in cols, f"tree_stats missing column {c}"
        db.close()

    def test_tree_stats_all_problems(self):
        probs = _load_problems()
        pids = {p["id"] for p in probs["problems"]}
        db = sqlite3.connect(DB_PATH)
        cur = db.execute("SELECT problem_id FROM tree_stats")
        db_pids = {row[0] for row in cur.fetchall()}
        db.close()
        for pid in pids:
            assert pid in db_pids, (
                f"tree_stats missing entry for {pid}"
            )

    def test_tree_stats_reasonable_values(self):
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        cur = db.execute("SELECT * FROM tree_stats")
        rows = cur.fetchall()
        db.close()
        for row in rows:
            pid = row["problem_id"]
            assert row["nodes_evaluated"] > 0, (
                f"{pid}: nodes_evaluated must be > 0"
            )
            assert row["unique_positions"] > 0, (
                f"{pid}: unique_positions must be > 0"
            )
            assert row["max_depth"] > 0, (
                f"{pid}: max_depth must be > 0"
            )
            assert row["branching_factor"] > 0, (
                f"{pid}: branching_factor must be > 0"
            )
            assert row["nodes_evaluated"] >= row["unique_positions"], (
                f"{pid}: nodes_evaluated should be >= unique_positions"
            )
