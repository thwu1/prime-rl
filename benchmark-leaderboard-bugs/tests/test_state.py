
import csv
import json
import math
import os
import subprocess

import duckdb
import pytest

DATA_DIR = "/app/data"
DB_PATH = os.path.join(DATA_DIR, "benchmark.db")
CSV_PATH = os.path.join(DATA_DIR, "similarity.csv")
OUTPUT_FILE = "/app/output/leaderboard.json"
SIMILARITY_THRESHOLD = 0.8


# ---------------------------------------------------------------------------
# Reference data loaders (independent of the pipeline under test)
# ---------------------------------------------------------------------------

def _load_models_from_db():
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT name, release_date FROM models").fetchall()
    conn.close()
    return [{"name": r["name"], "release_date": r["release_date"]} for r in rows]


def _load_tasks_from_db():
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, created_at, repo FROM tasks").fetchall()
    conn.close()
    return [{"id": r["id"], "created_at": r["created_at"], "repo": r["repo"]} for r in rows]


def _load_similarity_pairs():
    pairs = []
    with open(CSV_PATH) as f:
        reader = csv.DictReader(f)
        for row in reader:
            pairs.append((row["task_a"], row["task_b"], float(row["jaccard_similarity"])))
    return pairs


def _load_run_results(model_name, run_num):
    """Load run results from Parquet file using DuckDB."""
    path = os.path.join(DATA_DIR, "runs", f"{model_name}.parquet")
    col = f"r{run_num}"
    conn = duckdb.connect()
    rows = conn.execute(f"""
        SELECT instance_id, {col} AS resolved
        FROM read_parquet('{path}')
    """).fetchall()
    conn.close()
    results = {}
    for instance_id, resolved in rows:
        results[instance_id] = bool(resolved) if resolved is not None else False
    return results


def _load_all_runs(model_name):
    return [_load_run_results(model_name, i) for i in range(1, 6)]


# ---------------------------------------------------------------------------
# Reference metric computations
# ---------------------------------------------------------------------------

def _expected_resolved_rate(runs, task_ids):
    rates = []
    for run in runs:
        resolved = sum(1 for tid in task_ids if run.get(tid, False))
        rates.append(resolved / len(task_ids))
    return sum(rates) / len(rates)


def _expected_sem(runs, task_ids):
    rates = []
    for run in runs:
        resolved = sum(1 for tid in task_ids if run.get(tid, False))
        rates.append(resolved / len(task_ids))
    mean = sum(rates) / len(rates)
    n = len(rates)
    sample_var = sum((r - mean) ** 2 for r in rates) / (n - 1)
    return math.sqrt(sample_var) / math.sqrt(n)


def _expected_pass_at_k(runs, task_ids, k):
    n = len(runs)
    values = []
    for tid in task_ids:
        c = sum(1 for run in runs if run.get(tid, False))
        if n - c < k:
            values.append(1.0)
        else:
            values.append(1.0 - math.comb(n - c, k) / math.comb(n, k))
    return sum(values) / len(values)


def _expected_contamination_count(eval_tasks, all_tasks, model_release_date, similarity_pairs):
    """Compute contamination: temporal + one-hop similarity from temporal."""
    temporal = set()
    for t in all_tasks:
        if t["created_at"] < model_release_date:
            temporal.add(t["id"])

    sim_contam = set()
    for task_a, task_b, jaccard in similarity_pairs:
        if jaccard >= SIMILARITY_THRESHOLD:
            if task_a in temporal:
                sim_contam.add(task_b)
            if task_b in temporal:
                sim_contam.add(task_a)

    contaminated = temporal | sim_contam
    eval_ids = {t["id"] for t in eval_tasks}
    return len(contaminated & eval_ids)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def all_tasks():
    return _load_tasks_from_db()


@pytest.fixture(scope="module")
def all_models():
    return _load_models_from_db()


@pytest.fixture(scope="module")
def similarity_pairs():
    return _load_similarity_pairs()


@pytest.fixture(scope="module")
def all_results(all_models):
    return {m["name"]: _load_all_runs(m["name"]) for m in all_models}


@pytest.fixture(scope="module")
def leaderboard():
    os.makedirs("/app/output", exist_ok=True)
    result = subprocess.run(
        ["python3", "/app/src/pipeline.py", "--data-dir", DATA_DIR, "--output", OUTPUT_FILE],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, f"Pipeline failed:\n{result.stderr}"
    with open(OUTPUT_FILE) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Data Access Tests
# ---------------------------------------------------------------------------

class TestDataAccess:
    def test_reads_from_sqlite(self, leaderboard, all_models):
        """Pipeline must read model data from SQLite."""
        model_names = {m["name"] for m in all_models}
        lb_models = {r["model"] for r in leaderboard["rankings"]}
        assert model_names == lb_models

    def test_correct_task_count(self, leaderboard, all_tasks):
        assert leaderboard["num_tasks"] == len(all_tasks)


# ---------------------------------------------------------------------------
# Resolved Rate Tests
# ---------------------------------------------------------------------------

class TestResolvedRate:
    def test_all_resolved_rates(self, leaderboard, all_tasks, all_results):
        task_ids = [t["id"] for t in all_tasks]
        for entry in leaderboard["rankings"]:
            name = entry["model"]
            expected = _expected_resolved_rate(all_results[name], task_ids)
            assert abs(entry["resolved_rate"] - expected) < 1e-4, (
                f"{name}: resolved_rate expected {expected:.6f}, got {entry['resolved_rate']}"
            )

    def test_model_alpha_specific(self, leaderboard):
        alpha = next(r for r in leaderboard["rankings"] if r["model"] == "model-alpha")
        assert abs(alpha["resolved_rate"] - 5 / 60) < 1e-4

    def test_model_zeta_specific(self, leaderboard):
        zeta = next(r for r in leaderboard["rankings"] if r["model"] == "model-zeta")
        assert abs(zeta["resolved_rate"] - 53 / 60) < 1e-4


# ---------------------------------------------------------------------------
# SEM Tests
# ---------------------------------------------------------------------------

class TestSEM:
    def test_all_sems(self, leaderboard, all_tasks, all_results):
        task_ids = [t["id"] for t in all_tasks]
        for entry in leaderboard["rankings"]:
            name = entry["model"]
            expected = _expected_sem(all_results[name], task_ids)
            assert abs(entry["sem"] - expected) < 1e-4, (
                f"{name}: SEM expected {expected:.6f}, got {entry['sem']}"
            )

    def test_sem_uses_bessel_correction(self, leaderboard, all_tasks, all_results):
        """SEM must use n-1 denominator, not n."""
        task_ids = [t["id"] for t in all_tasks]
        for entry in leaderboard["rankings"]:
            name = entry["model"]
            runs = all_results[name]
            rates = []
            for run in runs:
                resolved = sum(1 for tid in task_ids if run.get(tid, False))
                rates.append(resolved / len(task_ids))
            mean = sum(rates) / len(rates)
            n = len(rates)

            pop_var = sum((r - mean) ** 2 for r in rates) / n
            pop_sem = math.sqrt(pop_var / n)

            sample_var = sum((r - mean) ** 2 for r in rates) / (n - 1)
            sample_sem = math.sqrt(sample_var / n)

            assert abs(entry["sem"] - sample_sem) < 1e-4, (
                f"{name}: SEM should use sample variance (n-1)"
            )


# ---------------------------------------------------------------------------
# Pass@k Tests
# ---------------------------------------------------------------------------

class TestPassAtK:
    def test_pass_at_1_equals_resolved_rate(self, leaderboard):
        for r in leaderboard["rankings"]:
            assert abs(r["pass_at_1"] - r["resolved_rate"]) < 1e-4, (
                f"{r['model']}: pass@1 should equal resolved_rate"
            )

    def test_pass_at_3(self, leaderboard, all_tasks, all_results):
        task_ids = [t["id"] for t in all_tasks]
        for entry in leaderboard["rankings"]:
            name = entry["model"]
            expected = _expected_pass_at_k(all_results[name], task_ids, 3)
            assert abs(entry["pass_at_3"] - expected) < 1e-4, (
                f"{name}: pass@3 expected {expected:.6f}, got {entry['pass_at_3']}"
            )

    def test_pass_at_5(self, leaderboard, all_tasks, all_results):
        task_ids = [t["id"] for t in all_tasks]
        for entry in leaderboard["rankings"]:
            name = entry["model"]
            expected = _expected_pass_at_k(all_results[name], task_ids, 5)
            assert abs(entry["pass_at_5"] - expected) < 1e-4, (
                f"{name}: pass@5 expected {expected:.6f}, got {entry['pass_at_5']}"
            )

    def test_unbiased_not_naive(self, leaderboard, all_tasks, all_results):
        """pass@3 must use unbiased estimator, not naive 1-(1-c/n)^k."""
        task_ids = [t["id"] for t in all_tasks]
        runs = all_results["model-alpha"]
        n = len(runs)

        naive_values = []
        for tid in task_ids:
            c = sum(1 for run in runs if run.get(tid, False))
            naive_values.append(1.0 - (1.0 - c / n) ** 3)
        naive_avg = sum(naive_values) / len(naive_values)

        unbiased_avg = _expected_pass_at_k(runs, task_ids, 3)
        assert abs(naive_avg - unbiased_avg) > 0.001, (
            "Test data issue: naive and unbiased should differ"
        )

        alpha = next(r for r in leaderboard["rankings"] if r["model"] == "model-alpha")
        assert abs(alpha["pass_at_3"] - unbiased_avg) < 1e-4, (
            "pass@3 should use unbiased estimator"
        )
        assert abs(alpha["pass_at_3"] - naive_avg) > 0.001, (
            "pass@3 appears to use naive formula"
        )


# ---------------------------------------------------------------------------
# Contamination Tests
# ---------------------------------------------------------------------------

class TestContamination:
    def test_all_contamination_counts(self, leaderboard, all_tasks, all_models,
                                       similarity_pairs):
        for entry in leaderboard["rankings"]:
            name = entry["model"]
            model = next(m for m in all_models if m["name"] == name)
            expected = _expected_contamination_count(
                all_tasks, all_tasks, model["release_date"], similarity_pairs
            )
            assert entry["num_contaminated_tasks"] == expected, (
                f"{name}: expected {expected} contaminated, "
                f"got {entry['num_contaminated_tasks']}"
            )

    def test_alpha_contamination(self, leaderboard):
        """model-alpha: 2 temporal (101,115) + 2 similarity (301,401) = 4."""
        alpha = next(r for r in leaderboard["rankings"] if r["model"] == "model-alpha")
        assert alpha["num_contaminated_tasks"] == 4

    def test_beta_contamination(self, leaderboard):
        """model-beta: 4 temporal + similarity gives 7 total."""
        beta = next(r for r in leaderboard["rankings"] if r["model"] == "model-beta")
        assert beta["num_contaminated_tasks"] == 7

    def test_gamma_contamination(self, leaderboard):
        """model-gamma: 6 temporal + 3 similarity (401,419,601) = 9."""
        gamma = next(r for r in leaderboard["rankings"] if r["model"] == "model-gamma")
        assert gamma["num_contaminated_tasks"] == 9

    def test_boundary_date_delta(self, leaderboard):
        """model-delta released 2026-02-01; task 419 created 2026-02-01.
        Same-day = NOT temporally contaminated. But 419 IS similarity-
        contaminated via 218 (Jaccard 0.83). Total = 9."""
        delta = next(r for r in leaderboard["rankings"] if r["model"] == "model-delta")
        assert delta["num_contaminated_tasks"] == 9

    def test_boundary_date_zeta(self, leaderboard):
        """model-zeta released 2026-05-15; task 612 created 2026-05-15.
        Same-day = NOT contaminated. Total = 11."""
        zeta = next(r for r in leaderboard["rankings"] if r["model"] == "model-zeta")
        assert zeta["num_contaminated_tasks"] == 11

    def test_no_transitive_similarity_propagation(self, leaderboard):
        """For model-alpha: 301 is similarity-contaminated (via 101), and
        301<->601 has Jaccard 0.82 >= 0.8. But 601 must NOT be contaminated
        because similarity propagation is one-hop from TEMPORAL only."""
        alpha = next(r for r in leaderboard["rankings"] if r["model"] == "model-alpha")
        assert alpha["num_contaminated_tasks"] == 4, (
            "model-alpha should have exactly 4 contaminated tasks "
            "(no transitive propagation)"
        )

    def test_below_threshold_not_propagated(self, leaderboard):
        """201<->501 Jaccard is 0.78 < 0.8; 515<->612 is 0.72 < 0.8."""
        epsilon = next(r for r in leaderboard["rankings"] if r["model"] == "model-epsilon")
        assert epsilon["num_contaminated_tasks"] == 11


# ---------------------------------------------------------------------------
# Time-Window Filtering Tests
# ---------------------------------------------------------------------------

class TestTimeWindowFilter:
    def _run_filtered(self, start_date, end_date, output_file):
        result = subprocess.run(
            [
                "python3", "/app/src/pipeline.py",
                "--data-dir", DATA_DIR,
                "--output", output_file,
                "--start-date", start_date,
                "--end-date", end_date,
            ],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, f"Filtered run failed:\n{result.stderr}"
        with open(output_file) as f:
            return json.load(f)

    def test_filtered_task_count(self, all_tasks):
        filtered = self._run_filtered("2025-09-01", "2026-02-15",
                                       "/app/output/leaderboard_filtered.json")
        expected_ids = [
            t["id"] for t in all_tasks
            if "2025-09-01" <= t["created_at"] <= "2026-02-15"
        ]
        assert filtered["num_tasks"] == len(expected_ids)

    def test_filtered_alpha_zero(self, all_tasks):
        """model-alpha solves none of the filtered tasks."""
        filtered = self._run_filtered("2025-09-01", "2026-02-15",
                                       "/app/output/leaderboard_f2.json")
        alpha = next(r for r in filtered["rankings"] if r["model"] == "model-alpha")
        assert alpha["resolved_rate"] == 0.0

    def test_filtered_zeta_rate(self, all_tasks, all_results):
        filtered = self._run_filtered("2025-09-01", "2026-02-15",
                                       "/app/output/leaderboard_f3.json")
        filtered_ids = [
            t["id"] for t in all_tasks
            if "2025-09-01" <= t["created_at"] <= "2026-02-15"
        ]
        expected = _expected_resolved_rate(all_results["model-zeta"], filtered_ids)
        zeta = next(r for r in filtered["rankings"] if r["model"] == "model-zeta")
        assert abs(zeta["resolved_rate"] - expected) < 1e-4

    def test_filtered_contamination_uses_full_temporal(self, all_tasks,
                                                        similarity_pairs):
        """Filtered contamination must use full task set for temporal checks."""
        filtered = self._run_filtered("2025-09-01", "2026-02-15",
                                       "/app/output/leaderboard_f4.json")
        delta = next(r for r in filtered["rankings"] if r["model"] == "model-delta")
        assert delta["num_contaminated_tasks"] == 4, (
            "Filtered delta should have 4 contaminated "
            "(301,322,401 temporal + 419 via similarity from 218)"
        )


# ---------------------------------------------------------------------------
# Schema and jq Validation Tests
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    def test_jq_parses_output(self, leaderboard):
        """Output must be valid JSON processable by jq."""
        result = subprocess.run(
            ["jq", ".rankings | length", OUTPUT_FILE],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"jq failed: {result.stderr}"
        assert int(result.stdout.strip()) == 6

    def test_jq_ranking_order(self, leaderboard):
        """Verify rankings are sorted descending via jq query."""
        result = subprocess.run(
            ["jq", "[.rankings[:-1] | to_entries[] | "
             ".value.resolved_rate >= .value.resolved_rate] | all",
             OUTPUT_FILE],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_required_fields(self, leaderboard):
        assert "time_window" in leaderboard
        assert "num_tasks" in leaderboard
        assert "rankings" in leaderboard
        assert "task_difficulty" in leaderboard

        for ranking in leaderboard["rankings"]:
            for field in [
                "rank", "model", "resolved_rate", "sem",
                "pass_at_1", "pass_at_3", "pass_at_5",
                "num_contaminated_tasks", "contamination_fraction",
            ]:
                assert field in ranking, (
                    f"Missing '{field}' for {ranking.get('model', '?')}"
                )

    def test_ranking_order(self, leaderboard):
        rankings = leaderboard["rankings"]
        for i in range(len(rankings) - 1):
            assert rankings[i]["resolved_rate"] >= rankings[i + 1]["resolved_rate"]

    def test_rank_numbers(self, leaderboard):
        for i, r in enumerate(leaderboard["rankings"]):
            assert r["rank"] == i + 1

    def test_num_runs(self, leaderboard):
        assert leaderboard["num_runs_per_model"] == 5


# ---------------------------------------------------------------------------
# Task Difficulty Tests
# ---------------------------------------------------------------------------

class TestTaskDifficulty:
    def test_difficulty_ascending(self, leaderboard):
        difficulties = leaderboard["task_difficulty"]
        for i in range(len(difficulties) - 1):
            assert difficulties[i]["mean_solve_rate"] <= difficulties[i + 1]["mean_solve_rate"], (
                "task_difficulty must be sorted ascending by mean_solve_rate"
            )

    def test_hardest_task(self, leaderboard):
        difficulties = leaderboard["task_difficulty"]
        assert difficulties[0]["task_id"] == "owner-f__repo-6-612"
        assert difficulties[0]["num_models_solved_at_least_once"] == 1

    def test_easiest_task(self, leaderboard):
        difficulties = leaderboard["task_difficulty"]
        assert difficulties[-1]["task_id"] == "owner-a__repo-1-101"
        assert difficulties[-1]["num_models_solved_at_least_once"] == 6


# ---------------------------------------------------------------------------
# Missing / Edge-Case Results
# ---------------------------------------------------------------------------

class TestMissingResults:
    def test_missing_entry_counts_as_failure(self, leaderboard, all_tasks, all_results):
        """model-gamma run 2 missing entry for task 515 must count as failure."""
        task_ids = [t["id"] for t in all_tasks]
        expected = _expected_resolved_rate(all_results["model-gamma"], task_ids)
        gamma = next(r for r in leaderboard["rankings"] if r["model"] == "model-gamma")
        assert abs(gamma["resolved_rate"] - expected) < 1e-4

    def test_error_status_no_resolved_key(self, leaderboard, all_tasks, all_results):
        """model-beta run 4 has an error entry without resolved key for task 201;
        must be treated as resolved=false."""
        task_ids = [t["id"] for t in all_tasks]
        expected = _expected_resolved_rate(all_results["model-beta"], task_ids)
        beta = next(r for r in leaderboard["rankings"] if r["model"] == "model-beta")
        assert abs(beta["resolved_rate"] - expected) < 1e-4
