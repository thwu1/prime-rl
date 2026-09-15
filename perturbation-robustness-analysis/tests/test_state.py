
import json
import math
import os
import sqlite3
import subprocess

import numpy as np
import pytest
from scipy import stats


# ---------------------------------------------------------------------------
# Helpers — load from SQLite with correct data cleaning
# ---------------------------------------------------------------------------

def get_db():
    return sqlite3.connect('/app/data/benchmark.db')


def load_sim_data():
    """Load deduplicated simulation data from SQLite.

    Deduplicates by (model, task_id, perturbation_id, rollout_id) before
    aggregating to per-condition success rates.
    """
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT model, perturbation_id, task_id,
               CAST(SUM(success) AS REAL) / COUNT(*) as success_rate
        FROM (
            SELECT DISTINCT model, task_id, perturbation_id, rollout_id, success
            FROM rollouts
        )
        GROUP BY model, perturbation_id, task_id
    ''')
    data = {}
    for model, pert_id, task_id, rate in c.fetchall():
        data.setdefault((model, pert_id), {})[task_id] = rate
    conn.close()
    return data


def load_real_data():
    """Load real-world data from SQLite, excluding calibration trials."""
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT model, task_id,
               CAST(SUM(success) AS REAL) / COUNT(*) as success_rate
        FROM real_trials
        WHERE trial_id >= 0
        GROUP BY model, task_id
    ''')
    data = {}
    for model, task_id, rate in c.fetchall():
        data.setdefault(model, {})[task_id] = rate
    conn.close()
    return data


def ref_hedges_g(default_rates, pert_rates):
    """Reference paired Hedges' g implementation."""
    diffs = np.array(default_rates) - np.array(pert_rates)
    n = len(diffs)
    if n <= 1:
        return 0.0
    sd = np.std(diffs, ddof=1)
    if sd < 1e-15:
        return 0.0
    d_z = np.mean(diffs) / sd
    df = n - 1
    J = 1.0 - 3.0 / (4.0 * df - 1.0)
    return float(J * d_z)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def sim_data():
    return load_sim_data()


@pytest.fixture(scope='session')
def real_data():
    return load_real_data()


@pytest.fixture(scope='session')
def task_ids(sim_data):
    first_key = next(iter(sim_data))
    return sorted(sim_data[first_key].keys())


@pytest.fixture(scope='session')
def model_names(sim_data):
    return sorted(set(k[0] for k in sim_data.keys()))


@pytest.fixture(scope='session', autouse=True)
def ensure_analysis_ran():
    """Run analyze.py if report.json does not yet exist."""
    if not os.path.exists('/app/output/report.json'):
        if os.path.exists('/app/analyze.py'):
            result = subprocess.run(
                ['python3', '/app/analyze.py'],
                capture_output=True, timeout=300, cwd='/app',
            )
            assert result.returncode == 0, (
                f"analyze.py failed with:\n{result.stderr.decode()}"
            )


@pytest.fixture(scope='session')
def report():
    with open('/app/output/report.json') as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Data quality sanity checks
# ---------------------------------------------------------------------------

class TestDataIntegrity:
    def test_database_has_duplicates(self):
        """Sanity: the raw database should contain duplicate rollouts."""
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            SELECT COUNT(*) FROM (
                SELECT model, task_id, perturbation_id, rollout_id
                FROM rollouts
                GROUP BY model, task_id, perturbation_id, rollout_id
                HAVING COUNT(*) > 1
            )
        ''')
        n_dup_groups = c.fetchone()[0]
        conn.close()
        assert n_dup_groups > 0, "Database should contain duplicate rollouts"

    def test_database_has_calibration_trials(self):
        """Sanity: the raw database should contain calibration trials."""
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM real_trials WHERE trial_id < 0')
        n_cal = c.fetchone()[0]
        conn.close()
        assert n_cal > 0, "Database should contain calibration trials"

    def test_deduped_rollout_counts(self):
        """After dedup, every (model, task, perturbation) must have exactly 25 rollouts."""
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            SELECT model, task_id, perturbation_id, COUNT(*) as n
            FROM (
                SELECT DISTINCT model, task_id, perturbation_id, rollout_id
                FROM rollouts
            )
            GROUP BY model, task_id, perturbation_id
        ''')
        for model, tid, pid, n in c.fetchall():
            assert n == 25, (
                f"Expected 25 unique rollouts for ({model}, task={tid}, pert={pid}), got {n}"
            )
        conn.close()


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------

class TestReportStructure:
    def test_report_exists(self):
        assert os.path.exists('/app/output/report.json'), \
            "report.json not found at /app/output/report.json"

    def test_top_level_keys(self, report):
        for key in ['effect_sizes', 'category_aggregates',
                     'real_to_sim_correlation', 'composite_robustness_index']:
            assert key in report, f"Missing top-level key: {key}"

    def test_effect_sizes_count(self, report):
        assert len(report['effect_sizes']) == 45, (
            f"Expected 45 effect size entries (3 models x 15 perturbations), "
            f"got {len(report['effect_sizes'])}"
        )

    def test_effect_size_entry_fields(self, report):
        for model in ['ModelA', 'ModelB', 'ModelC']:
            for pid in range(1, 16):
                key = f"{model}_pert{pid}"
                assert key in report['effect_sizes'], \
                    f"Missing effect size entry: {key}"
                entry = report['effect_sizes'][key]
                for field in ['hedges_g', 'ci_lower', 'ci_upper',
                              'perturbation', 'category']:
                    assert field in entry, \
                        f"Missing field '{field}' in {key}"


# ---------------------------------------------------------------------------
# Hedges' g tests
# ---------------------------------------------------------------------------

class TestHedgesG:
    def test_specific_values(self, report, sim_data, task_ids):
        """Verify Hedges' g against reference for selected perturbations."""
        for model in ['ModelA', 'ModelB', 'ModelC']:
            default_rates = [sim_data[(model, 0)][tid] for tid in task_ids]
            for pert_id in [1, 4, 5, 10, 13, 15]:
                pert_rates = [sim_data[(model, pert_id)][tid]
                              for tid in task_ids]
                expected = ref_hedges_g(default_rates, pert_rates)
                key = f"{model}_pert{pert_id}"
                actual = report['effect_sizes'][key]['hedges_g']
                assert abs(actual - expected) < 0.02, (
                    f"Hedges' g mismatch for {key}: "
                    f"expected {expected:.6f}, got {actual:.6f}"
                )

    def test_all_values_in_range(self, report):
        for key, entry in report['effect_sizes'].items():
            g = entry['hedges_g']
            assert -20 < g < 20, f"Unreasonable Hedges' g for {key}: {g}"

    def test_large_perturbation_positive(self, report):
        """VSB-NOBJ (pert 15) should have positive g for all models."""
        for model in ['ModelA', 'ModelB', 'ModelC']:
            key = f"{model}_pert15"
            g = report['effect_sizes'][key]['hedges_g']
            assert g > 0.1, (
                f"Expected substantial positive Hedges' g for "
                f"VSB-NOBJ on {model}, got {g:.4f}"
            )


# ---------------------------------------------------------------------------
# Bootstrap CI tests
# ---------------------------------------------------------------------------

class TestBootstrapCI:
    def test_ci_contains_estimate(self, report):
        for key, entry in report['effect_sizes'].items():
            lo = entry['ci_lower']
            hi = entry['ci_upper']
            g = entry['hedges_g']
            assert lo <= g + 1e-3, \
                f"CI lower {lo:.4f} > estimate {g:.4f} for {key}"
            assert hi >= g - 1e-3, \
                f"CI upper {hi:.4f} < estimate {g:.4f} for {key}"

    def test_ci_positive_width(self, report):
        for key, entry in report['effect_sizes'].items():
            width = entry['ci_upper'] - entry['ci_lower']
            assert width > 0, f"CI width non-positive for {key}"
            assert width < 30, \
                f"CI width unreasonably large ({width:.2f}) for {key}"

    def test_ci_not_just_percentile(self, report):
        """BCa CIs should differ from naive percentile CIs."""
        asymmetric_count = 0
        for key, entry in report['effect_sizes'].items():
            g = entry['hedges_g']
            lo = entry['ci_lower']
            hi = entry['ci_upper']
            left = g - lo
            right = hi - g
            if left > 0 and right > 0:
                ratio = left / right
                if ratio < 0.85 or ratio > 1.18:
                    asymmetric_count += 1
        assert asymmetric_count >= 5, (
            f"Only {asymmetric_count} CIs show asymmetry — "
            f"BCa may not be implemented correctly"
        )


# ---------------------------------------------------------------------------
# Spearman correlation tests
# ---------------------------------------------------------------------------

class TestSpearmanCorrelation:
    def test_rho_value(self, report, sim_data, real_data,
                       task_ids, model_names):
        sim_vals, real_vals = [], []
        for model in model_names:
            for tid in task_ids:
                if model in real_data and tid in real_data[model]:
                    sim_vals.append(sim_data[(model, 0)][tid])
                    real_vals.append(real_data[model][tid])

        expected_rho, _ = stats.spearmanr(sim_vals, real_vals)
        actual_rho = report['real_to_sim_correlation']['spearman_rho']
        assert abs(actual_rho - expected_rho) < 0.02, (
            f"Spearman rho mismatch: "
            f"expected {expected_rho:.6f}, got {actual_rho:.6f}"
        )

    def test_p_value_significant(self, report):
        p = report['real_to_sim_correlation']['p_value']
        assert 0 < p < 0.05, f"Expected significant p-value, got {p}"

    def test_fisher_ci_valid(self, report):
        corr = report['real_to_sim_correlation']
        lo = corr['fisher_z_ci_lower']
        hi = corr['fisher_z_ci_upper']
        rho = corr['spearman_rho']
        assert -1 <= lo < rho, f"Fisher CI lower bound invalid: {lo}"
        assert rho < hi <= 1, f"Fisher CI upper bound invalid: {hi}"

    def test_fisher_ci_width(self, report):
        corr = report['real_to_sim_correlation']
        width = corr['fisher_z_ci_upper'] - corr['fisher_z_ci_lower']
        assert 0.05 < width < 1.0, \
            f"Fisher CI width unreasonable: {width}"

    def test_n_pairs(self, report):
        assert report['real_to_sim_correlation']['n_pairs'] == 24


# ---------------------------------------------------------------------------
# Category aggregate tests
# ---------------------------------------------------------------------------

class TestCategoryAggregates:
    def test_all_categories_present(self, report):
        expected = {'Visual', 'Semantic', 'Behavioral',
                    'Cross-SB', 'Cross-VB', 'Cross-VSB'}
        for model in ['ModelA', 'ModelB', 'ModelC']:
            assert model in report['category_aggregates']
            actual = set(report['category_aggregates'][model].keys())
            assert actual == expected, (
                f"Category set mismatch for {model}: "
                f"expected {expected}, got {actual}"
            )

    def test_visual_aggregate_consistent(self, report):
        """Visual category aggregate = mean of perturbations 1-4."""
        for model in ['ModelA', 'ModelB', 'ModelC']:
            gs = [report['effect_sizes'][f"{model}_pert{p}"]['hedges_g']
                  for p in [1, 2, 3, 4]]
            expected = float(np.mean(gs))
            actual = report['category_aggregates'][model]['Visual']
            assert abs(actual - expected) < 0.01, (
                f"Visual aggregate mismatch for {model}: "
                f"expected {expected:.6f}, got {actual:.6f}"
            )

    def test_semantic_aggregate_consistent(self, report):
        for model in ['ModelA', 'ModelB', 'ModelC']:
            gs = [report['effect_sizes'][f"{model}_pert{p}"]['hedges_g']
                  for p in [5, 6, 7, 8, 9]]
            expected = float(np.mean(gs))
            actual = report['category_aggregates'][model]['Semantic']
            assert abs(actual - expected) < 0.01

    def test_behavioral_equals_single(self, report):
        """Behavioral category has only perturbation 10."""
        for model in ['ModelA', 'ModelB', 'ModelC']:
            expected = report['effect_sizes'][f"{model}_pert10"]['hedges_g']
            actual = report['category_aggregates'][model]['Behavioral']
            assert abs(actual - expected) < 0.001


# ---------------------------------------------------------------------------
# Composite Robustness Index tests
# ---------------------------------------------------------------------------

class TestCRI:
    def test_all_models_present(self, report):
        for model in ['ModelA', 'ModelB', 'ModelC']:
            assert model in report['composite_robustness_index']
            assert isinstance(
                report['composite_robustness_index'][model], (int, float))

    def test_cri_reference_values(self, report, sim_data, task_ids):
        """Verify CRI matches independently computed reference."""
        pert_ids = list(range(1, 16))

        for model in ['ModelA', 'ModelB', 'ModelC']:
            all_rel_drops = []
            per_pert_means = []

            for pid in pert_ids:
                drops = []
                for tid in task_ids:
                    d = sim_data[(model, 0)][tid]
                    p = sim_data[(model, pid)][tid]
                    rel_drop = (d - p) / d if d > 0 else 0.0
                    all_rel_drops.append(rel_drop)
                    drops.append(rel_drop)
                per_pert_means.append(float(np.mean(drops)))

            mean_drop = float(np.mean(all_rel_drops))

            sorted_desc = sorted(all_rel_drops, reverse=True)
            k = max(1, math.ceil(0.10 * len(sorted_desc)))
            cvar = float(np.mean(sorted_desc[:k]))

            m = float(np.mean(per_pert_means))
            s = float(np.std(per_pert_means, ddof=1))
            cv = s / abs(m) if abs(m) > 1e-10 else 0.0

            expected_cri = (0.5 * (1 - mean_drop)
                            + 0.3 * (1 - cvar)
                            + 0.2 * (1 - cv))
            actual_cri = report['composite_robustness_index'][model]

            assert abs(actual_cri - expected_cri) < 0.02, (
                f"CRI mismatch for {model}: "
                f"expected {expected_cri:.6f}, got {actual_cri:.6f}"
            )

    def test_cri_ordering_plausible(self, report):
        cris = report['composite_robustness_index']
        for model, val in cris.items():
            assert math.isfinite(val), \
                f"CRI for {model} is not finite: {val}"


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------

class TestReproducibility:
    def test_analyze_script_exists(self):
        assert os.path.exists('/app/analyze.py'), \
            "analyze.py not found at /app/analyze.py"

    def test_analyze_produces_output(self):
        """Run analyze.py fresh and verify it produces valid JSON."""
        report_path = '/app/output/report.json'
        backup = None
        if os.path.exists(report_path):
            with open(report_path) as f:
                backup = f.read()

        try:
            os.makedirs('/app/output', exist_ok=True)
            if os.path.exists(report_path):
                os.remove(report_path)
            result = subprocess.run(
                ['python3', '/app/analyze.py'],
                capture_output=True, timeout=300, cwd='/app',
            )
            assert result.returncode == 0, (
                f"analyze.py failed:\n{result.stderr.decode()[:2000]}"
            )
            assert os.path.exists(report_path), \
                "analyze.py did not produce report.json"
            with open(report_path) as f:
                data = json.load(f)
            assert isinstance(data, dict)
        finally:
            if backup is not None:
                with open(report_path, 'w') as f:
                    f.write(backup)
