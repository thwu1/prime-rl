
import json
import os
import sqlite3
import pytest

REPORT_PATH = "/app/dse_report.json"
JSONL_PATH = "/app/validated_solutions.jsonl"
DB_PATH = "/app/synthesis.db"


@pytest.fixture
def report():
    assert os.path.exists(REPORT_PATH), f"Output file {REPORT_PATH} does not exist"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture
def jsonl_lines():
    assert os.path.exists(JSONL_PATH), f"JSONL file {JSONL_PATH} does not exist"
    with open(JSONL_PATH) as f:
        lines = [l.strip() for l in f if l.strip()]
    return lines


@pytest.fixture
def db():
    assert os.path.exists(DB_PATH), f"SQLite database {DB_PATH} does not exist"
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ── JSONL validation ────────────────────────────────────────────────────────

class TestJSONL:
    def test_line_count(self, jsonl_lines):
        assert len(jsonl_lines) == 24, f"Expected 24 JSONL lines, got {len(jsonl_lines)}"

    def test_valid_json_per_line(self, jsonl_lines):
        for i, line in enumerate(jsonl_lines):
            try:
                json.loads(line)
            except json.JSONDecodeError:
                pytest.fail(f"Line {i} is not valid JSON: {line[:80]}")

    def test_required_fields(self, jsonl_lines):
        required = {"model", "category", "module", "solution_index",
                     "pass_status", "lut", "ff", "dsp", "bram", "io"}
        for i, line in enumerate(jsonl_lines):
            obj = json.loads(line)
            missing = required - set(obj.keys())
            assert not missing, f"Line {i} missing fields: {missing}"

    def test_solution_index_is_integer(self, jsonl_lines):
        for i, line in enumerate(jsonl_lines):
            obj = json.loads(line)
            assert isinstance(obj["solution_index"], int), \
                f"Line {i}: solution_index must be int, got {type(obj['solution_index'])}"

    def test_alpha_parity_sol0(self, jsonl_lines):
        for line in jsonl_lines:
            obj = json.loads(line)
            if (obj["model"] == "model_alpha" and obj["module"] == "parity_8bit"
                    and obj["solution_index"] == 0):
                assert obj["lut"] == 2
                assert obj["ff"] == 0
                assert obj["dsp"] == 0
                assert obj["bram"] == 0
                assert obj["pass_status"] == "true"
                return
        pytest.fail("model_alpha parity_8bit solution_index=0 not found in JSONL")

    def test_null_resource_for_empty_optimized(self, jsonl_lines):
        """alpha parity sol2 has empty optimized dict -> null resources"""
        for line in jsonl_lines:
            obj = json.loads(line)
            if (obj["model"] == "model_alpha" and obj["module"] == "parity_8bit"
                    and obj["solution_index"] == 2):
                assert obj["lut"] is None
                assert obj["ff"] is None
                assert obj["dsp"] is None
                assert obj["bram"] is None
                return
        pytest.fail("alpha parity sol2 not found in JSONL")

    def test_null_lut_preserved(self, jsonl_lines):
        """beta bin_mult sol2 has LUT=null in optimized"""
        for line in jsonl_lines:
            obj = json.loads(line)
            if (obj["model"] == "model_beta" and obj["module"] == "bin_mult_4bit"
                    and obj["solution_index"] == 2):
                assert obj["lut"] is None
                assert obj["ff"] == 0
                return
        pytest.fail("beta bin_mult sol2 not found in JSONL")

    def test_whitespace_pass_preserved(self, jsonl_lines):
        """beta parity sol2 has pass='  true  ' — raw value preserved"""
        for line in jsonl_lines:
            obj = json.loads(line)
            if (obj["model"] == "model_beta" and obj["module"] == "parity_8bit"
                    and obj["solution_index"] == 2):
                assert obj["pass_status"].strip() == "true"
                return
        pytest.fail("beta parity sol2 not found in JSONL")


# ── SQLite database validation ──────────────────────────────────────────────

class TestSQLiteDatabase:
    def test_solutions_table_exists(self, db):
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='solutions'")
        assert cur.fetchone() is not None, "Table 'solutions' does not exist"

    def test_solutions_row_count(self, db):
        cur = db.execute("SELECT COUNT(*) FROM solutions")
        assert cur.fetchone()[0] == 24

    def test_valid_solutions_count(self, db):
        cur = db.execute("SELECT COUNT(*) FROM solutions WHERE is_valid = 1")
        assert cur.fetchone()[0] == 20

    def test_invalid_solutions_count(self, db):
        cur = db.execute("SELECT COUNT(*) FROM solutions WHERE is_valid = 0")
        assert cur.fetchone()[0] == 4

    def test_valid_cost_gamma_parity_sol0(self, db):
        cur = db.execute(
            "SELECT weighted_cost FROM solutions "
            "WHERE model='model_gamma' AND module='parity_8bit' AND solution_index=0")
        row = cur.fetchone()
        assert row is not None
        assert abs(row[0] - 1.0) < 0.01

    def test_valid_cost_beta_binmult_sol0(self, db):
        cur = db.execute(
            "SELECT weighted_cost FROM solutions "
            "WHERE model='model_beta' AND module='bin_mult_4bit' AND solution_index=0")
        row = cur.fetchone()
        assert row is not None
        assert abs(row[0] - 30.0) < 0.01

    def test_invalid_null_cost(self, db):
        cur = db.execute(
            "SELECT weighted_cost FROM solutions "
            "WHERE model='model_alpha' AND module='parity_8bit' AND solution_index=2")
        row = cur.fetchone()
        assert row is not None
        assert row[0] is None, "Invalid solution should have NULL weighted_cost"

    def test_false_pass_invalid(self, db):
        cur = db.execute(
            "SELECT is_valid FROM solutions "
            "WHERE model='model_beta' AND module='bin_mult_4bit' AND solution_index=1")
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 0, "Solution with pass='false' should be invalid"

    def test_null_resource_invalid(self, db):
        cur = db.execute(
            "SELECT is_valid FROM solutions "
            "WHERE model='model_beta' AND module='bin_mult_4bit' AND solution_index=2")
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 0, "Solution with null LUT should be invalid"

    def test_pareto_solutions_exists(self, db):
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE name='pareto_solutions'")
        assert cur.fetchone() is not None, "'pareto_solutions' table/view does not exist"

    def test_pareto_total_count(self, db):
        cur = db.execute("SELECT COUNT(*) FROM pareto_solutions")
        assert cur.fetchone()[0] == 6

    def test_pareto_parity_members(self, db):
        cur = db.execute(
            "SELECT model, solution_index FROM pareto_solutions WHERE module='parity_8bit'")
        rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0]["model"] == "model_gamma"
        assert rows[0]["solution_index"] == 0

    def test_pareto_binmult_count(self, db):
        cur = db.execute(
            "SELECT COUNT(*) FROM pareto_solutions WHERE module='bin_mult_4bit'")
        assert cur.fetchone()[0] == 3

    def test_pareto_fsm_count(self, db):
        cur = db.execute(
            "SELECT COUNT(*) FROM pareto_solutions WHERE module='fsm_counter_8bit'")
        assert cur.fetchone()[0] == 2

    def test_module_stats_exists(self, db):
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE name='module_stats'")
        assert cur.fetchone() is not None, "'module_stats' table/view does not exist"

    def test_module_stats_parity(self, db):
        cur = db.execute(
            "SELECT total_valid, pareto_count, best_cost, worst_cost "
            "FROM module_stats WHERE module='parity_8bit'")
        row = cur.fetchone()
        assert row is not None
        assert row["total_valid"] == 7
        assert row["pareto_count"] == 1
        assert abs(row["best_cost"] - 1.0) < 0.01
        assert abs(row["worst_cost"] - 4.5) < 0.01

    def test_module_stats_binmult(self, db):
        cur = db.execute(
            "SELECT total_valid, pareto_count, best_cost, worst_cost "
            "FROM module_stats WHERE module='bin_mult_4bit'")
        row = cur.fetchone()
        assert row is not None
        assert row["total_valid"] == 6
        assert row["pareto_count"] == 3
        assert abs(row["best_cost"] - 15.0) < 0.01
        assert abs(row["worst_cost"] - 114.0) < 0.01

    def test_module_stats_fsm(self, db):
        cur = db.execute(
            "SELECT total_valid, pareto_count, best_cost, worst_cost "
            "FROM module_stats WHERE module='fsm_counter_8bit'")
        row = cur.fetchone()
        assert row is not None
        assert row["total_valid"] == 7
        assert row["pareto_count"] == 2
        assert abs(row["best_cost"] - 5.5) < 0.01
        assert abs(row["worst_cost"] - 8.5) < 0.01


# ── Report structure tests ─────────────────────────────────────────────────

class TestStructure:
    def test_top_level_keys(self, report):
        assert "modules" in report
        assert "model_summary" in report

    def test_module_names(self, report):
        modules = set(report["modules"].keys())
        expected = {"parity_8bit", "bin_mult_4bit", "fsm_counter_8bit"}
        assert modules == expected

    def test_model_names(self, report):
        models = set(report["model_summary"].keys())
        expected = {"model_alpha", "model_beta", "model_gamma"}
        assert models == expected


# ── parity_8bit ─────────────────────────────────────────────────────────────

class TestParityModule:
    def test_total_passing(self, report):
        assert report["modules"]["parity_8bit"]["total_passing"] == 7

    def test_pareto_size(self, report):
        assert report["modules"]["parity_8bit"]["pareto_frontier_size"] == 1

    def test_pareto_member(self, report):
        pf = report["modules"]["parity_8bit"]["pareto_frontier"]
        assert len(pf) == 1
        assert pf[0]["model"] == "model_gamma"
        assert pf[0]["solution_index"] == 0
        assert pf[0]["LUT"] == 1
        assert pf[0]["FF"] == 0
        assert pf[0]["DSP"] == 0
        assert pf[0]["BRAM"] == 0

    def test_best_cost(self, report):
        assert report["modules"]["parity_8bit"]["best_cost"] == pytest.approx(1.0)

    def test_cost_spread(self, report):
        assert report["modules"]["parity_8bit"]["cost_spread"] == pytest.approx(3.5)

    def test_ranking_order(self, report):
        rankings = report["modules"]["parity_8bit"]["rankings"]
        assert len(rankings) == 7

        assert rankings[0]["rank"] == 1
        assert rankings[0]["model"] == "model_gamma"
        assert rankings[0]["solution_index"] == 0
        assert rankings[0]["weighted_cost"] == pytest.approx(1.0)
        assert rankings[0]["is_pareto"] is True

        assert rankings[1]["rank"] == 2
        assert rankings[1]["model"] == "model_beta"
        assert rankings[1]["solution_index"] == 2
        assert rankings[1]["weighted_cost"] == pytest.approx(2.0)
        assert rankings[1]["is_pareto"] is False

        assert rankings[2]["rank"] == 3
        assert rankings[2]["model"] == "model_alpha"
        assert rankings[2]["solution_index"] == 0
        assert rankings[2]["weighted_cost"] == pytest.approx(2.0)

        assert rankings[3]["rank"] == 4
        assert rankings[3]["model"] == "model_beta"
        assert rankings[3]["solution_index"] == 0

        assert rankings[6]["rank"] == 7
        assert rankings[6]["model"] == "model_beta"
        assert rankings[6]["solution_index"] == 1
        assert rankings[6]["weighted_cost"] == pytest.approx(4.5)

    def test_hypervolume(self, report):
        assert report["modules"]["parity_8bit"]["hypervolume"] == pytest.approx(12.0)


# ── bin_mult_4bit ───────────────────────────────────────────────────────────

class TestBinMultModule:
    def test_total_passing(self, report):
        assert report["modules"]["bin_mult_4bit"]["total_passing"] == 6

    def test_pareto_size(self, report):
        assert report["modules"]["bin_mult_4bit"]["pareto_frontier_size"] == 3

    def test_pareto_members(self, report):
        pf = report["modules"]["bin_mult_4bit"]["pareto_frontier"]
        pf_set = {(p["model"], p["solution_index"]) for p in pf}
        expected = {
            ("model_alpha", 2),
            ("model_beta", 0),
            ("model_gamma", 1),
        }
        assert pf_set == expected

    def test_best_cost(self, report):
        assert report["modules"]["bin_mult_4bit"]["best_cost"] == pytest.approx(15.0)

    def test_cost_spread(self, report):
        assert report["modules"]["bin_mult_4bit"]["cost_spread"] == pytest.approx(99.0)

    def test_ranking_order(self, report):
        rankings = report["modules"]["bin_mult_4bit"]["rankings"]
        assert len(rankings) == 6
        costs = [r["weighted_cost"] for r in rankings]
        assert costs == sorted(costs), "Rankings must be sorted by ascending cost"

        assert rankings[0]["weighted_cost"] == pytest.approx(15.0)
        assert rankings[0]["model"] == "model_alpha"
        assert rankings[0]["solution_index"] == 2
        assert rankings[0]["is_pareto"] is True

        assert rankings[-1]["weighted_cost"] == pytest.approx(114.0)
        assert rankings[-1]["model"] == "model_gamma"
        assert rankings[-1]["solution_index"] == 1
        assert rankings[-1]["is_pareto"] is True

    def test_hypervolume(self, report):
        assert report["modules"]["bin_mult_4bit"]["hypervolume"] == pytest.approx(35.0)


# ── fsm_counter_8bit ────────────────────────────────────────────────────────

class TestFsmCounterModule:
    def test_total_passing(self, report):
        assert report["modules"]["fsm_counter_8bit"]["total_passing"] == 7

    def test_pareto_size(self, report):
        assert report["modules"]["fsm_counter_8bit"]["pareto_frontier_size"] == 2

    def test_pareto_members(self, report):
        pf = report["modules"]["fsm_counter_8bit"]["pareto_frontier"]
        pf_set = {(p["model"], p["solution_index"]) for p in pf}
        expected = {
            ("model_beta", 0),
            ("model_gamma", 1),
        }
        assert pf_set == expected

    def test_best_cost(self, report):
        assert report["modules"]["fsm_counter_8bit"]["best_cost"] == pytest.approx(5.5)

    def test_cost_spread(self, report):
        assert report["modules"]["fsm_counter_8bit"]["cost_spread"] == pytest.approx(3.0)

    def test_ranking_top4(self, report):
        rankings = report["modules"]["fsm_counter_8bit"]["rankings"]
        assert len(rankings) == 7

        assert rankings[0]["model"] == "model_beta"
        assert rankings[0]["solution_index"] == 0
        assert rankings[0]["weighted_cost"] == pytest.approx(5.5)
        assert rankings[0]["is_pareto"] is True

        assert rankings[1]["model"] == "model_gamma"
        assert rankings[1]["solution_index"] == 1
        assert rankings[1]["weighted_cost"] == pytest.approx(6.0)
        assert rankings[1]["is_pareto"] is True

        assert rankings[2]["model"] == "model_gamma"
        assert rankings[2]["solution_index"] == 0
        assert rankings[2]["weighted_cost"] == pytest.approx(6.0)
        assert rankings[2]["is_pareto"] is False

        assert rankings[3]["model"] == "model_gamma"
        assert rankings[3]["solution_index"] == 2
        assert rankings[3]["weighted_cost"] == pytest.approx(6.5)

    def test_ranking_bottom(self, report):
        rankings = report["modules"]["fsm_counter_8bit"]["rankings"]

        assert rankings[4]["model"] == "model_alpha"
        assert rankings[4]["solution_index"] == 1
        assert rankings[4]["weighted_cost"] == pytest.approx(7.0)

        assert rankings[5]["model"] == "model_alpha"
        assert rankings[5]["solution_index"] == 0
        assert rankings[5]["weighted_cost"] == pytest.approx(7.0)

        assert rankings[6]["model"] == "model_beta"
        assert rankings[6]["solution_index"] == 1
        assert rankings[6]["weighted_cost"] == pytest.approx(8.5)

    def test_hypervolume(self, report):
        assert report["modules"]["fsm_counter_8bit"]["hypervolume"] == pytest.approx(21.0)


# ── Model summary ──────────────────────────────────────────────────────────

class TestModelSummary:
    def test_alpha_totals(self, report):
        alpha = report["model_summary"]["model_alpha"]
        assert alpha["total_passing"] == 7
        assert alpha["total_pareto"] == 1

    def test_alpha_pareto_fraction(self, report):
        alpha = report["model_summary"]["model_alpha"]
        assert alpha["pareto_fraction"] == pytest.approx(1.0 / 7.0, rel=1e-3)

    def test_alpha_avg_cost(self, report):
        alpha = report["model_summary"]["model_alpha"]
        assert alpha["avg_weighted_cost"] == pytest.approx(86.0 / 7.0, rel=1e-3)

    def test_alpha_avg_nre(self, report):
        alpha = report["model_summary"]["model_alpha"]
        assert alpha["avg_nre"] == pytest.approx(0.6605, rel=1e-2)

    def test_beta_totals(self, report):
        beta = report["model_summary"]["model_beta"]
        assert beta["total_passing"] == 6
        assert beta["total_pareto"] == 2

    def test_beta_pareto_fraction(self, report):
        beta = report["model_summary"]["model_beta"]
        assert beta["pareto_fraction"] == pytest.approx(2.0 / 6.0, rel=1e-3)

    def test_beta_avg_cost(self, report):
        beta = report["model_summary"]["model_beta"]
        assert beta["avg_weighted_cost"] == pytest.approx(52.5 / 6.0, rel=1e-3)

    def test_beta_avg_nre(self, report):
        beta = report["model_summary"]["model_beta"]
        assert beta["avg_nre"] == pytest.approx(0.5616, rel=1e-2)

    def test_gamma_totals(self, report):
        gamma = report["model_summary"]["model_gamma"]
        assert gamma["total_passing"] == 7
        assert gamma["total_pareto"] == 3

    def test_gamma_pareto_fraction(self, report):
        gamma = report["model_summary"]["model_gamma"]
        assert gamma["pareto_fraction"] == pytest.approx(3.0 / 7.0, rel=1e-3)

    def test_gamma_avg_cost(self, report):
        gamma = report["model_summary"]["model_gamma"]
        assert gamma["avg_weighted_cost"] == pytest.approx(154.0 / 7.0, rel=1e-3)

    def test_gamma_avg_nre(self, report):
        gamma = report["model_summary"]["model_gamma"]
        assert gamma["avg_nre"] == pytest.approx(0.7206, rel=1e-2)


# ── Edge case tests ─────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_null_resource_excluded(self, report):
        """model_beta bin_mult_4bit sol2 with null LUT should be excluded"""
        bin_mult = report["modules"]["bin_mult_4bit"]
        for r in bin_mult["rankings"]:
            if r["model"] == "model_beta":
                assert r["solution_index"] != 2, \
                    "Solution with null resources should be excluded"

    def test_failed_solution_excluded(self, report):
        """model_alpha parity_8bit sol2 with error string should be excluded"""
        parity = report["modules"]["parity_8bit"]
        for r in parity["rankings"]:
            if r["model"] == "model_alpha":
                assert r["solution_index"] != 2, \
                    "Failed solution should be excluded"

    def test_empty_resource_excluded(self, report):
        """model_gamma parity_8bit sol1 with empty optimized dict should be excluded"""
        parity = report["modules"]["parity_8bit"]
        for r in parity["rankings"]:
            if r["model"] == "model_gamma":
                assert r["solution_index"] != 1, \
                    "Solution with empty resources should be excluded"

    def test_whitespace_pass_included(self, report):
        """model_beta parity_8bit sol2 with pass='  true  ' should be included"""
        parity = report["modules"]["parity_8bit"]
        found = any(
            r["model"] == "model_beta" and r["solution_index"] == 2
            for r in parity["rankings"]
        )
        assert found, "Solution with whitespace-padded 'true' pass should be included"

    def test_uppercase_pass_included(self, report):
        """model_gamma parity_8bit sol2 with pass='TRUE' should be included"""
        parity = report["modules"]["parity_8bit"]
        found = any(
            r["model"] == "model_gamma" and r["solution_index"] == 2
            for r in parity["rankings"]
        )
        assert found, "Solution with uppercase 'TRUE' pass should be included"

    def test_rankings_consecutive_ranks(self, report):
        """Rankings must use 1-based consecutive integers"""
        for module_name, module_data in report["modules"].items():
            rankings = module_data["rankings"]
            for i, r in enumerate(rankings):
                assert r["rank"] == i + 1, \
                    f"Rank mismatch in {module_name}: expected {i + 1}, got {r['rank']}"

    def test_pareto_frontier_sorted(self, report):
        """Pareto frontier entries should be sorted by weighted_cost"""
        for module_name, module_data in report["modules"].items():
            pf = module_data["pareto_frontier"]
            costs = [p["weighted_cost"] for p in pf]
            assert costs == sorted(costs), \
                f"Pareto frontier in {module_name} not sorted by cost"

    def test_false_pass_excluded(self, report):
        """model_beta bin_mult_4bit sol1 with pass='false' should be excluded"""
        bin_mult = report["modules"]["bin_mult_4bit"]
        for r in bin_mult["rankings"]:
            if r["model"] == "model_beta":
                assert r["solution_index"] != 1, \
                    "Solution with pass='false' should be excluded"
