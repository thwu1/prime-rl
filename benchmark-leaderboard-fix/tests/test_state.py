
"""Tests for the multi-tool benchmark evaluation pipeline."""

import json
import os
import subprocess
import sys
from math import comb

import pytest

sys.path.insert(0, "/app/pipeline")


# ---------------------------------------------------------------------------
# Stage 1: SQL Extraction (sqlite3 CLI)
# ---------------------------------------------------------------------------


class TestSQLExtraction:
    """Verify sqlite3 extraction query produces correct JSON structure."""

    @pytest.fixture(autouse=True)
    def extract(self):
        result = subprocess.run(
            ["sqlite3", "/app/eval.db"],
            stdin=open("/app/pipeline/extract.sql"),
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"sqlite3 failed: {result.stderr}"
        output = result.stdout.strip()
        assert output != "TODO", "extract.sql is still a stub"
        self.data = json.loads(output)

    def test_top_level_keys(self):
        assert "models" in self.data
        assert "tasks" in self.data
        assert "evaluations" in self.data

    def test_model_count(self):
        assert len(self.data["models"]) == 5

    def test_task_count(self):
        assert len(self.data["tasks"]) == 10

    def test_evaluation_count(self):
        assert len(self.data["evaluations"]) == 50

    def test_pricing_pivoted_to_dict(self):
        """Pricing table must be pivoted from row-per-tier to a dict."""
        alpha = next(m for m in self.data["models"] if m["model_id"] == "alpha-v1")
        assert isinstance(alpha["pricing"], dict), \
            f"pricing should be dict, got {type(alpha['pricing'])}"
        assert "input_per_mtok" in alpha["pricing"]
        assert "cached_input_per_mtok" in alpha["pricing"]
        assert "output_per_mtok" in alpha["pricing"]

    def test_pricing_values(self):
        alpha = next(m for m in self.data["models"] if m["model_id"] == "alpha-v1")
        assert alpha["pricing"]["input_per_mtok"] == pytest.approx(3.0)
        assert alpha["pricing"]["cached_input_per_mtok"] == pytest.approx(0.3)
        assert alpha["pricing"]["output_per_mtok"] == pytest.approx(15.0)

    def test_epsilon_pricing(self):
        eps = next(m for m in self.data["models"] if m["model_id"] == "epsilon-7b")
        assert eps["pricing"]["input_per_mtok"] == pytest.approx(0.5)
        assert eps["pricing"]["cached_input_per_mtok"] == pytest.approx(0.05)
        assert eps["pricing"]["output_per_mtok"] == pytest.approx(2.5)

    def test_resolved_is_json_boolean(self):
        """SQLite stores booleans as integers; SQL must output JSON booleans."""
        for ev in self.data["evaluations"]:
            for run in ev["runs"]:
                assert isinstance(run["resolved"], bool), \
                    f"resolved should be bool, got {type(run['resolved'])}: {run['resolved']}"

    def test_runs_per_evaluation(self):
        for ev in self.data["evaluations"]:
            assert len(ev["runs"]) == 5, \
                f"{ev['model_id']}/{ev['task_id']} should have 5 runs"

    def test_model_has_release_date(self):
        for m in self.data["models"]:
            assert "release_date" in m
            assert len(m["release_date"]) == 10

    def test_token_fields_present(self):
        for ev in self.data["evaluations"]:
            for run in ev["runs"]:
                assert "input_tokens" in run
                assert "cached_tokens" in run
                assert "output_tokens" in run

    def test_success_count_alpha(self):
        """Verify alpha-v1 has exactly 5 total resolved runs."""
        alpha_evals = [e for e in self.data["evaluations"]
                       if e["model_id"] == "alpha-v1"]
        total = sum(1 for e in alpha_evals for r in e["runs"] if r["resolved"])
        assert total == 5


# ---------------------------------------------------------------------------
# Stage 2: Python Metrics — pass@k
# ---------------------------------------------------------------------------


class TestPassAtK:
    """Tests for the pass@k unbiased estimator."""

    @pytest.fixture(autouse=True)
    def load(self):
        from compute_metrics import compute_pass_at_k
        self.compute = compute_pass_at_k

    def test_all_fail(self):
        assert self.compute(5, 0, 5) == 0.0

    def test_all_pass(self):
        assert self.compute(5, 5, 5) == 1.0

    def test_one_success_n_equals_k(self):
        # Complete sample must include the success → 1.0
        assert self.compute(5, 1, 5) == 1.0

    def test_pass_at_3_c1(self):
        # 1 - C(4,3)/C(5,3) = 1 - 4/10 = 0.6
        assert self.compute(5, 1, 3) == pytest.approx(0.6, abs=1e-9)

    def test_pass_at_3_c2(self):
        # 1 - C(3,3)/C(5,3) = 1 - 1/10 = 0.9
        assert self.compute(5, 2, 3) == pytest.approx(0.9, abs=1e-9)

    def test_larger_n(self):
        expected = 1.0 - comb(7, 5) / comb(10, 5)
        assert self.compute(10, 3, 5) == pytest.approx(expected, abs=1e-9)

    def test_n8_c2_k4(self):
        expected = 1.0 - comb(6, 4) / comb(8, 4)
        assert self.compute(8, 2, 4) == pytest.approx(expected, abs=1e-9)

    def test_k_greater_than_n(self):
        assert self.compute(3, 1, 5) == 1.0
        assert self.compute(3, 0, 5) == 0.0

    def test_not_bernoulli(self):
        """Bernoulli power rule gives wrong answer for n=k."""
        exact = self.compute(5, 1, 5)
        bernoulli = 1.0 - (1.0 - 1 / 5) ** 5
        assert exact != pytest.approx(bernoulli, abs=0.01)

    def test_not_bayesian(self):
        """Bayesian Beta posterior gives wrong answer."""
        exact = self.compute(5, 1, 3)
        bayesian = 1.0 - (5 * 6 * 7) / (7 * 8 * 9)
        assert exact != pytest.approx(bayesian, abs=0.01)


# ---------------------------------------------------------------------------
# Stage 2: Python Metrics — SEM
# ---------------------------------------------------------------------------


class TestSEM:
    """Tests for SEM with Bessel's correction."""

    @pytest.fixture(autouse=True)
    def load(self):
        from compute_metrics import compute_sem
        self.compute = compute_sem

    def test_sem_basic(self):
        expected = (0.1 * 0.9 / 49) ** 0.5
        assert self.compute(5, 50) == pytest.approx(expected, abs=1e-9)

    def test_sem_half(self):
        expected = (0.25 / 49) ** 0.5
        assert self.compute(25, 50) == pytest.approx(expected, abs=1e-9)

    def test_all_pass(self):
        assert self.compute(50, 50) == 0.0

    def test_all_fail(self):
        assert self.compute(0, 50) == 0.0

    def test_differs_from_population(self):
        """Must use n-1 (Bessel), not n (population formula)."""
        naive = (0.2 * 0.8 / 50) ** 0.5
        corrected = (0.2 * 0.8 / 49) ** 0.5
        result = self.compute(10, 50)
        assert result == pytest.approx(corrected, abs=1e-9)
        assert result != pytest.approx(naive, abs=1e-6)

    def test_differs_from_clustered(self):
        """Must not apply design-effect correction."""
        corrected = (0.2 * 0.8 / 49) ** 0.5
        deff = 1 + (5 - 1) * 0.05
        clustered = (0.2 * 0.8 * deff / 49) ** 0.5
        result = self.compute(10, 50)
        assert result == pytest.approx(corrected, abs=1e-9)
        assert result != pytest.approx(clustered, abs=1e-6)

    def test_small_sample(self):
        assert self.compute(1, 2) == pytest.approx(0.5, abs=1e-9)


# ---------------------------------------------------------------------------
# Stage 2: Python Metrics — Cost
# ---------------------------------------------------------------------------


class TestCost:
    """Tests for tiered cost computation with cached pricing."""

    @pytest.fixture(autouse=True)
    def load(self):
        from compute_metrics import compute_cost_per_problem
        self.compute = compute_cost_per_problem

    def test_with_caching(self):
        runs = [{"input_tokens": 1000000, "cached_tokens": 800000,
                 "output_tokens": 50000}]
        pricing = {"input_per_mtok": 3.0, "cached_input_per_mtok": 0.3,
                   "output_per_mtok": 15.0}
        assert self.compute(runs, pricing) == pytest.approx(1.59, abs=1e-6)

    def test_not_ignoring_cache(self):
        runs = [{"input_tokens": 1000000, "cached_tokens": 800000,
                 "output_tokens": 50000}]
        pricing = {"input_per_mtok": 3.0, "cached_input_per_mtok": 0.3,
                   "output_per_mtok": 15.0}
        result = self.compute(runs, pricing)
        assert result != pytest.approx(3.75, abs=0.01)

    def test_no_caching(self):
        runs = [{"input_tokens": 500000, "cached_tokens": 0,
                 "output_tokens": 30000}]
        pricing = {"input_per_mtok": 2.0, "cached_input_per_mtok": 0.2,
                   "output_per_mtok": 10.0}
        assert self.compute(runs, pricing) == pytest.approx(1.3, abs=1e-6)

    def test_multiple_runs_averaged(self):
        runs = [
            {"input_tokens": 1000000, "cached_tokens": 900000,
             "output_tokens": 40000},
            {"input_tokens": 1000000, "cached_tokens": 700000,
             "output_tokens": 60000},
        ]
        pricing = {"input_per_mtok": 2.0, "cached_input_per_mtok": 0.5,
                   "output_per_mtok": 10.0}
        assert self.compute(runs, pricing) == pytest.approx(1.3, abs=1e-6)


# ---------------------------------------------------------------------------
# Stage 2: Python Metrics — Contamination
# ---------------------------------------------------------------------------


class TestContamination:
    """Tests for contamination detection logic."""

    @pytest.fixture(autouse=True)
    def load(self):
        from compute_metrics import is_contaminated, get_clean_task_ids
        self.is_contaminated = is_contaminated
        self.get_clean = get_clean_task_ids

    def test_before_release_contaminated(self):
        assert self.is_contaminated("2024-11-15", "2025-01-15") is True

    def test_after_release_clean(self):
        assert self.is_contaminated("2025-02-28", "2025-01-15") is False

    def test_same_day_clean(self):
        assert self.is_contaminated("2025-01-15", "2025-01-15") is False

    def test_day_before_contaminated(self):
        assert self.is_contaminated("2025-01-14", "2025-01-15") is True

    def test_clean_task_ids(self):
        tasks = [
            {"task_id": "t1", "created_at": "2024-11-15"},
            {"task_id": "t2", "created_at": "2025-01-10"},
            {"task_id": "t3", "created_at": "2025-01-15"},
            {"task_id": "t4", "created_at": "2025-03-20"},
        ]
        clean = self.get_clean(tasks, "2025-01-15")
        assert "t1" not in clean
        assert "t2" not in clean
        assert "t3" in clean
        assert "t4" in clean


# ---------------------------------------------------------------------------
# Stage 2: Python Metrics — Unique Solves
# ---------------------------------------------------------------------------


class TestUniqueSolves:
    """Tests for unique solve computation."""

    @pytest.fixture(autouse=True)
    def load(self):
        from compute_metrics import compute_unique_solves
        self.compute = compute_unique_solves

    def test_basic(self):
        evaluations = [
            {"model_id": "A", "task_id": "t1", "runs": [{"resolved": True}]},
            {"model_id": "A", "task_id": "t2", "runs": [{"resolved": True}]},
            {"model_id": "B", "task_id": "t1", "runs": [{"resolved": True}]},
            {"model_id": "B", "task_id": "t2", "runs": [{"resolved": False}]},
            {"model_id": "B", "task_id": "t3", "runs": [{"resolved": True}]},
        ]
        result = self.compute(evaluations, [{"model_id": "A"}, {"model_id": "B"}])
        assert result["A"] == 1
        assert result["B"] == 1

    def test_none(self):
        evaluations = [
            {"model_id": "A", "task_id": "t1", "runs": [{"resolved": True}]},
            {"model_id": "B", "task_id": "t1", "runs": [{"resolved": True}]},
        ]
        result = self.compute(evaluations, [{"model_id": "A"}, {"model_id": "B"}])
        assert result["A"] == 0
        assert result["B"] == 0

    def test_any_run_counts(self):
        evaluations = [
            {"model_id": "A", "task_id": "t1", "runs": [
                {"resolved": False}, {"resolved": False}, {"resolved": True}]},
            {"model_id": "B", "task_id": "t1", "runs": [
                {"resolved": False}, {"resolved": False}]},
        ]
        result = self.compute(evaluations, [{"model_id": "A"}, {"model_id": "B"}])
        assert result["A"] == 1
        assert result["B"] == 0

    def test_with_pipeline_data(self):
        """Verify unique solves on the actual evaluation dataset."""
        result = subprocess.run(
            ["sqlite3", "/app/eval.db"],
            stdin=open("/app/pipeline/extract.sql"),
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            pytest.skip("extract.sql not working")
        data = json.loads(result.stdout.strip())
        result = self.compute(data["evaluations"], data["models"])
        assert result["delta-coder"] == 1
        assert result["epsilon-7b"] == 1
        assert result["alpha-v1"] == 0
        assert result["beta-2"] == 0
        assert result["gamma-3b"] == 0


# ---------------------------------------------------------------------------
# Stage 3: jq Ranking
# ---------------------------------------------------------------------------


class TestJqRanking:
    """Verify jq ranking filter produces correct output."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.tmp = tmp_path

    def _run_jq(self, metrics, config):
        metrics_file = self.tmp / "metrics.json"
        config_file = self.tmp / "config.json"
        metrics_file.write_text(json.dumps(metrics))
        config_file.write_text(json.dumps(config))
        result = subprocess.run(
            ["jq", "--slurpfile", "config", str(config_file),
             "-f", "/app/pipeline/rank_and_validate.jq", str(metrics_file)],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"jq failed: {result.stderr}"
        out = result.stdout.strip()
        assert out != '"TODO"', "rank_and_validate.jq is still a stub"
        return json.loads(out)

    def _make_entry(self, model_id, rr, sem, pk, cost=1.0, cc=0, drr=0.0, us=0):
        return {"model_id": model_id, "resolved_rate": rr, "sem": sem,
                "pass_at_k": pk, "cost_per_problem": cost,
                "contaminated_count": cc,
                "decontaminated_resolved_rate": drr, "unique_solves": us}

    def test_basic_ranking(self):
        config = {"ranking": {
            "primary_sort": {"field": "resolved_rate", "order": "descending"},
            "tiebreakers": [{"field": "sem", "order": "ascending"}]}}
        metrics = [
            self._make_entry("A", 0.3, 0.05, 0.4),
            self._make_entry("B", 0.7, 0.03, 0.8),
        ]
        result = self._run_jq(metrics, config)
        assert result[0]["model_id"] == "B"
        assert result[1]["model_id"] == "A"
        assert result[0]["rank"] == 1
        assert result[1]["rank"] == 2

    def test_ascending_sort_not_hardcoded(self):
        """Verify ranking uses config, not hardcoded descending."""
        config = {"ranking": {
            "primary_sort": {"field": "resolved_rate", "order": "ascending"},
            "tiebreakers": []}}
        metrics = [
            self._make_entry("A", 0.3, 0.05, 0.4),
            self._make_entry("B", 0.7, 0.03, 0.8),
        ]
        result = self._run_jq(metrics, config)
        assert result[0]["model_id"] == "A"
        assert result[1]["model_id"] == "B"

    def test_tiebreaker_sem(self):
        """When resolved_rate tied, lower SEM should win."""
        config = {"ranking": {
            "primary_sort": {"field": "resolved_rate", "order": "descending"},
            "tiebreakers": [{"field": "sem", "order": "ascending"}]}}
        metrics = [
            self._make_entry("A", 0.5, 0.06, 0.7),
            self._make_entry("B", 0.5, 0.03, 0.7),
        ]
        result = self._run_jq(metrics, config)
        assert result[0]["model_id"] == "B"

    def test_tiebreaker_cascade(self):
        config = {"ranking": {
            "primary_sort": {"field": "resolved_rate", "order": "descending"},
            "tiebreakers": [
                {"field": "sem", "order": "ascending"},
                {"field": "pass_at_k", "order": "descending"}]}}
        metrics = [
            self._make_entry("A", 0.5, 0.03, 0.6),
            self._make_entry("B", 0.5, 0.03, 0.9),
        ]
        result = self._run_jq(metrics, config)
        assert result[0]["model_id"] == "B"

    def test_output_format_fields(self):
        config = {"ranking": {
            "primary_sort": {"field": "resolved_rate", "order": "descending"},
            "tiebreakers": []}}
        metrics = [self._make_entry("X", 0.5, 0.04, 0.6, 1.5, 3, 0.4, 1)]
        result = self._run_jq(metrics, config)
        entry = result[0]
        assert "resolved_rate_pct" in entry
        assert "sem_pct" in entry
        assert "pass_at_k_pct" in entry
        assert "cost_per_problem" in entry
        assert "contaminated_count" in entry
        assert "decontaminated_resolved_rate_pct" in entry
        assert "unique_solves" in entry
        assert entry["resolved_rate_pct"] == pytest.approx(50.0, abs=0.1)
        assert entry["sem_pct"] == pytest.approx(4.0, abs=0.01)
        assert entry["pass_at_k_pct"] == pytest.approx(60.0, abs=0.1)


# ---------------------------------------------------------------------------
# Full Pipeline Integration (make all)
# ---------------------------------------------------------------------------


class TestPipeline:
    """End-to-end pipeline test via make."""

    @pytest.fixture(autouse=True)
    def run_pipeline(self):
        subprocess.run(["make", "-C", "/app", "clean"],
                       capture_output=True, timeout=10)
        result = subprocess.run(
            ["make", "-C", "/app", "all"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, \
            f"make failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        with open("/app/output/leaderboard.json") as f:
            self.leaderboard = json.load(f)

    def test_ranking_order(self):
        ids = [e["model_id"] for e in self.leaderboard]
        assert ids == [
            "epsilon-7b", "delta-coder", "gamma-3b", "beta-2", "alpha-v1"]

    def test_resolved_rates(self):
        rates = {e["model_id"]: e["resolved_rate_pct"] for e in self.leaderboard}
        assert rates["alpha-v1"] == pytest.approx(10.0, abs=0.1)
        assert rates["beta-2"] == pytest.approx(20.0, abs=0.1)
        assert rates["gamma-3b"] == pytest.approx(42.0, abs=0.1)
        assert rates["delta-coder"] == pytest.approx(60.0, abs=0.1)
        assert rates["epsilon-7b"] == pytest.approx(68.0, abs=0.1)

    def test_sem_values(self):
        sems = {e["model_id"]: e["sem_pct"] for e in self.leaderboard}
        assert sems["alpha-v1"] == pytest.approx(4.29, abs=0.02)
        assert sems["beta-2"] == pytest.approx(5.71, abs=0.02)
        assert sems["epsilon-7b"] == pytest.approx(6.66, abs=0.02)

    def test_pass_at_5_values(self):
        pk = {e["model_id"]: e["pass_at_k_pct"] for e in self.leaderboard}
        assert pk["alpha-v1"] == pytest.approx(40.0, abs=0.1)
        assert pk["beta-2"] == pytest.approx(60.0, abs=0.1)
        assert pk["gamma-3b"] == pytest.approx(80.0, abs=0.1)
        assert pk["delta-coder"] == pytest.approx(90.0, abs=0.1)
        assert pk["epsilon-7b"] == pytest.approx(90.0, abs=0.1)

    def test_contamination_counts(self):
        counts = {e["model_id"]: e["contaminated_count"]
                  for e in self.leaderboard}
        assert counts["alpha-v1"] == 3
        assert counts["beta-2"] == 5
        assert counts["gamma-3b"] == 7
        assert counts["delta-coder"] == 8
        assert counts["epsilon-7b"] == 10

    def test_decontaminated_rates(self):
        rates = {e["model_id"]: e["decontaminated_resolved_rate_pct"]
                 for e in self.leaderboard}
        assert rates["alpha-v1"] == pytest.approx(5.7, abs=0.2)
        assert rates["beta-2"] == pytest.approx(4.0, abs=0.2)
        assert rates["delta-coder"] == pytest.approx(20.0, abs=0.2)

    def test_cost_values(self):
        costs = {e["model_id"]: e["cost_per_problem"]
                 for e in self.leaderboard}
        assert costs["alpha-v1"] == pytest.approx(1.704, abs=0.01)
        assert costs["beta-2"] == pytest.approx(1.45, abs=0.01)
        assert costs["gamma-3b"] == pytest.approx(0.9165, abs=0.01)
        assert costs["delta-coder"] == pytest.approx(3.2625, abs=0.01)
        assert costs["epsilon-7b"] == pytest.approx(0.365, abs=0.01)

    def test_unique_solves(self):
        solves = {e["model_id"]: e["unique_solves"]
                  for e in self.leaderboard}
        assert solves["delta-coder"] == 1
        assert solves["epsilon-7b"] == 1
        assert solves["alpha-v1"] == 0
        assert solves["beta-2"] == 0
        assert solves["gamma-3b"] == 0

    def test_output_structure(self):
        assert isinstance(self.leaderboard, list)
        assert len(self.leaderboard) == 5
        for entry in self.leaderboard:
            assert "rank" in entry
            assert "model_id" in entry
            assert "resolved_rate_pct" in entry
            assert "sem_pct" in entry
            assert "pass_at_k_pct" in entry
            assert "cost_per_problem" in entry

    def test_intermediate_files_created(self):
        """Verify the multi-stage pipeline produced intermediate artifacts."""
        assert os.path.exists("/app/intermediate/extracted.json"), \
            "Stage 1 (sqlite3) did not produce extracted.json"
        assert os.path.exists("/app/intermediate/metrics.json"), \
            "Stage 2 (python) did not produce metrics.json"
        assert os.path.exists("/app/intermediate/config.json"), \
            "Config was not converted to JSON"
