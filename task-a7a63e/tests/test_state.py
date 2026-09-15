"""Independent verification of sim-to-real evaluation metrics."""

import json
import math
import os
import sqlite3

import numpy as np
from scipy import stats
import pytest


# ---------------------------------------------------------------------------
# Independent reference helpers
# ---------------------------------------------------------------------------

def _ranks_desc(values):
    """Descending ranks (1 = highest) with average tie-breaking."""
    n = len(values)
    order = sorted(range(n), key=lambda i: -values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and values[order[j + 1]] == values[order[j]]:
            j += 1
        avg = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _mrv(sim_vals, real_vals):
    """Maximum Ranking Violation for one task."""
    sr = _ranks_desc(sim_vals)
    rr = _ranks_desc(real_vals)
    mv = 0.0
    for i in range(len(sim_vals)):
        for j in range(len(sim_vals)):
            if sr[i] < sr[j] and rr[i] > rr[j]:
                mv = max(mv, rr[i] - rr[j])
    return mv


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def expected():
    """Independently compute all expected results from the SQLite database."""
    conn = sqlite3.connect('/app/eval.db')
    c = conn.cursor()

    # Find production experiment
    c.execute("SELECT id FROM experiments WHERE status='production'")
    prod_id = c.fetchone()[0]

    # Tasks and policies (sorted alphabetically)
    c.execute("SELECT id, name FROM tasks ORDER BY name")
    tasks_rows = c.fetchall()
    task_ids = {name: tid for tid, name in tasks_rows}
    tasks = [name for _, name in tasks_rows]

    c.execute("SELECT id, name FROM policies ORDER BY name")
    pol_rows = c.fetchall()
    policy_ids = {name: pid for pid, name in pol_rows}
    policies = [name for _, name in pol_rows]

    # Real-world data
    real = {}
    for t in tasks:
        real[t] = {}
        for p in policies:
            c.execute(
                "SELECT success_rate FROM real_results "
                "WHERE experiment_id=? AND task_id=? AND policy_id=?",
                (prod_id, task_ids[t], policy_ids[p]))
            real[t][p] = c.fetchone()[0]

    # Visual matching approach
    c.execute("SELECT id FROM approaches WHERE name='visual_matching'")
    vm_aid = c.fetchone()[0]

    vm = {}
    for t in tasks:
        vm[t] = {}
        for p in policies:
            c.execute(
                "SELECT success_rate FROM sim_results "
                "WHERE experiment_id=? AND approach_id=? AND variant_id IS NULL "
                "AND task_id=? AND policy_id=?",
                (prod_id, vm_aid, task_ids[t], policy_ids[p]))
            vm[t][p] = c.fetchone()[0]

    # Variant aggregation
    c.execute("SELECT id FROM approaches WHERE name='variant_aggregation'")
    va_aid = c.fetchone()[0]

    c.execute("SELECT id, weight FROM variants WHERE approach_id=? ORDER BY id",
              (va_aid,))
    var_info = c.fetchall()

    va = {}
    for t in tasks:
        va[t] = {}
        for p in policies:
            vals = []
            wts = []
            for vid, w in var_info:
                c.execute(
                    "SELECT success_rate FROM sim_results "
                    "WHERE experiment_id=? AND approach_id=? AND variant_id=? "
                    "AND task_id=? AND policy_id=?",
                    (prod_id, va_aid, vid, task_ids[t], policy_ids[p]))
                sr = c.fetchone()[0]
                vals.append(sr)
                wts.append(w)
            valid = [(v, w) for v, w in zip(vals, wts) if v is not None]
            total_w = sum(w for _, w in valid)
            va[t][p] = sum(v * w / total_w for v, w in valid)

    # Bootstrap config
    c.execute("SELECT value FROM analysis_config WHERE key='bootstrap_seed'")
    bootstrap_seed = int(c.fetchone()[0])
    c.execute("SELECT value FROM analysis_config WHERE key='bootstrap_iterations'")
    bootstrap_n = int(c.fetchone()[0])

    conn.close()

    # Compute metrics for each approach
    out = {}
    for name, sim in [('visual_matching', vm), ('variant_aggregation', va)]:
        sf, rf = [], []
        for t in tasks:
            for p in policies:
                sf.append(sim[t][p])
                rf.append(real[t][p])

        sa = np.array(sf)
        ra = np.array(rf)

        # MMRV
        mrvs = [
            _mrv([sim[t][p] for p in policies], [real[t][p] for p in policies])
            for t in tasks
        ]
        mmrv = sum(mrvs) / len(mrvs)

        # Pearson
        pr, pp = stats.pearsonr(sa, ra)

        # Kendall tau-b
        kt, _ = stats.kendalltau(sa, ra)

        # Per-task Pearson
        ptp = {}
        for t in tasks:
            ts = [sim[t][p] for p in policies]
            tr = [real[t][p] for p in policies]
            if len(set(ts)) == 1:
                ptp[t] = None
            else:
                r, _ = stats.pearsonr(ts, tr)
                ptp[t] = round(float(r), 4)

        # Fisher z-transform mean (exclude null)
        valid_rs = [v for v in ptp.values() if v is not None]
        z_vals = [np.arctanh(r) for r in valid_rs]
        fz_mean = float(np.tanh(np.mean(z_vals)))

        # NRMSE
        rmse = math.sqrt(float(np.mean((sa - ra) ** 2)))
        nrmse = rmse / float(np.max(ra) - np.min(ra))

        # Bias
        bias = float(np.mean(sa - ra))

        # Bootstrap CI for Pearson r
        rng = np.random.default_rng(bootstrap_seed)
        n = len(sf)
        boot_rs = []
        for _ in range(bootstrap_n):
            idx = rng.integers(0, n, size=n)
            bs = sa[idx]
            br = ra[idx]
            if np.std(bs) > 0 and np.std(br) > 0:
                r_val, _ = stats.pearsonr(bs, br)
                if not np.isnan(r_val):
                    boot_rs.append(r_val)
        ci_lo = float(np.percentile(boot_rs, 2.5))
        ci_hi = float(np.percentile(boot_rs, 97.5))

        out[name] = {
            'mmrv': round(float(mmrv), 4),
            'pearson_r': round(float(pr), 4),
            'pearson_p': round(float(pp), 6),
            'kendall_tau_b': round(float(kt), 4),
            'nrmse': round(float(nrmse), 4),
            'bias': round(float(bias), 4),
            'per_task_pearson': ptp,
            'fisher_z_mean_r': round(fz_mean, 4),
            'ci_lower': round(ci_lo, 4),
            'ci_upper': round(ci_hi, 4),
        }

    vm_r = out['visual_matching']['pearson_r']
    va_r = out['variant_aggregation']['pearson_r']
    out['comparison'] = {
        'better_approach': 'visual_matching' if vm_r >= va_r else 'variant_aggregation',
        'mmrv_difference': round(
            out['visual_matching']['mmrv'] - out['variant_aggregation']['mmrv'], 4),
        'pearson_difference': round(vm_r - va_r, 4),
    }
    return out


@pytest.fixture(scope='module')
def agent():
    """Load agent's results."""
    path = '/app/results.json'
    assert os.path.exists(path), "results.json not found at /app/results.json"
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------

class TestFileAndStructure:
    def test_results_file_exists(self):
        assert os.path.exists('/app/results.json'), "Missing /app/results.json"

    def test_valid_json(self):
        with open('/app/results.json') as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_top_level_keys(self, agent):
        for key in ['visual_matching', 'variant_aggregation', 'comparison']:
            assert key in agent, f"Missing top-level key: {key}"

    def test_approach_metric_keys(self, agent):
        required = ['mmrv', 'pearson_r', 'pearson_p', 'kendall_tau_b',
                     'per_task_pearson', 'nrmse', 'bias',
                     'fisher_z_mean_r', 'pearson_r_ci_95']
        for approach in ['visual_matching', 'variant_aggregation']:
            for key in required:
                assert key in agent[approach], f"Missing {key} in {approach}"

    def test_comparison_keys(self, agent):
        for key in ['better_approach', 'mmrv_difference', 'pearson_difference']:
            assert key in agent['comparison'], f"Missing {key} in comparison"

    def test_ci_is_list_of_two(self, agent):
        for approach in ['visual_matching', 'variant_aggregation']:
            ci = agent[approach]['pearson_r_ci_95']
            assert isinstance(ci, list) and len(ci) == 2, \
                f"{approach} pearson_r_ci_95 must be a list of [lower, upper]"


# ---------------------------------------------------------------------------
# Visualization tests
# ---------------------------------------------------------------------------

class TestVisualization:
    def test_plot_file_exists(self):
        assert os.path.exists('/app/plots/sim_vs_real.png'), \
            "Missing scatter plot at /app/plots/sim_vs_real.png"

    def test_plot_is_valid_png(self):
        with open('/app/plots/sim_vs_real.png', 'rb') as f:
            header = f.read(8)
        assert header[:4] == b'\x89PNG', "Plot file is not a valid PNG"

    def test_plot_reasonable_size(self):
        size = os.path.getsize('/app/plots/sim_vs_real.png')
        assert size > 1024, \
            f"Plot file too small ({size} bytes), likely empty or corrupt"
        assert size < 10_000_000, \
            f"Plot file too large ({size} bytes)"


# ---------------------------------------------------------------------------
# MMRV tests
# ---------------------------------------------------------------------------

class TestMMRV:
    def test_vm_mmrv(self, agent, expected):
        assert abs(agent['visual_matching']['mmrv'] - expected['visual_matching']['mmrv']) < 0.01, \
            f"VM MMRV: got {agent['visual_matching']['mmrv']}, expected {expected['visual_matching']['mmrv']}"

    def test_va_mmrv(self, agent, expected):
        assert abs(agent['variant_aggregation']['mmrv'] - expected['variant_aggregation']['mmrv']) < 0.01, \
            f"VA MMRV: got {agent['variant_aggregation']['mmrv']}, expected {expected['variant_aggregation']['mmrv']}"

    def test_vm_mmrv_nonnegative(self, agent):
        assert agent['visual_matching']['mmrv'] >= 0, "MMRV must be >= 0"

    def test_va_mmrv_nonnegative(self, agent):
        assert agent['variant_aggregation']['mmrv'] >= 0, "MMRV must be >= 0"


# ---------------------------------------------------------------------------
# Pearson tests
# ---------------------------------------------------------------------------

class TestPearson:
    def test_vm_pearson_r(self, agent, expected):
        assert abs(agent['visual_matching']['pearson_r'] - expected['visual_matching']['pearson_r']) < 0.01, \
            f"VM Pearson r: got {agent['visual_matching']['pearson_r']}, expected {expected['visual_matching']['pearson_r']}"

    def test_va_pearson_r(self, agent, expected):
        assert abs(agent['variant_aggregation']['pearson_r'] - expected['variant_aggregation']['pearson_r']) < 0.01, \
            f"VA Pearson r: got {agent['variant_aggregation']['pearson_r']}, expected {expected['variant_aggregation']['pearson_r']}"

    def test_vm_pearson_p(self, agent, expected):
        assert abs(agent['visual_matching']['pearson_p'] - expected['visual_matching']['pearson_p']) < 1e-4, \
            f"VM Pearson p: got {agent['visual_matching']['pearson_p']}, expected {expected['visual_matching']['pearson_p']}"

    def test_va_pearson_p_significant(self, agent):
        assert agent['variant_aggregation']['pearson_p'] < 0.05, \
            "VA Pearson should be significant (p < 0.05)"


# ---------------------------------------------------------------------------
# Kendall tests
# ---------------------------------------------------------------------------

class TestKendall:
    def test_vm_kendall(self, agent, expected):
        assert abs(agent['visual_matching']['kendall_tau_b'] - expected['visual_matching']['kendall_tau_b']) < 0.02, \
            f"VM Kendall: got {agent['visual_matching']['kendall_tau_b']}, expected {expected['visual_matching']['kendall_tau_b']}"

    def test_va_kendall(self, agent, expected):
        assert abs(agent['variant_aggregation']['kendall_tau_b'] - expected['variant_aggregation']['kendall_tau_b']) < 0.02, \
            f"VA Kendall: got {agent['variant_aggregation']['kendall_tau_b']}, expected {expected['variant_aggregation']['kendall_tau_b']}"


# ---------------------------------------------------------------------------
# NRMSE tests
# ---------------------------------------------------------------------------

class TestNRMSE:
    def test_vm_nrmse(self, agent, expected):
        assert abs(agent['visual_matching']['nrmse'] - expected['visual_matching']['nrmse']) < 0.02, \
            f"VM NRMSE: got {agent['visual_matching']['nrmse']}, expected {expected['visual_matching']['nrmse']}"

    def test_va_nrmse(self, agent, expected):
        assert abs(agent['variant_aggregation']['nrmse'] - expected['variant_aggregation']['nrmse']) < 0.02, \
            f"VA NRMSE: got {agent['variant_aggregation']['nrmse']}, expected {expected['variant_aggregation']['nrmse']}"


# ---------------------------------------------------------------------------
# Bias tests
# ---------------------------------------------------------------------------

class TestBias:
    def test_vm_bias(self, agent, expected):
        assert abs(agent['visual_matching']['bias'] - expected['visual_matching']['bias']) < 0.02, \
            f"VM Bias: got {agent['visual_matching']['bias']}, expected {expected['visual_matching']['bias']}"

    def test_va_bias(self, agent, expected):
        assert abs(agent['variant_aggregation']['bias'] - expected['variant_aggregation']['bias']) < 0.02, \
            f"VA Bias: got {agent['variant_aggregation']['bias']}, expected {expected['variant_aggregation']['bias']}"


# ---------------------------------------------------------------------------
# Per-task Pearson tests
# ---------------------------------------------------------------------------

class TestPerTaskPearson:
    def test_vm_all_tasks_present(self, agent, expected):
        exp_tasks = set(expected['visual_matching']['per_task_pearson'].keys())
        agent_tasks = set(agent['visual_matching']['per_task_pearson'].keys())
        assert exp_tasks == agent_tasks, \
            f"VM task mismatch: expected {exp_tasks}, got {agent_tasks}"

    def test_va_all_tasks_present(self, agent, expected):
        exp_tasks = set(expected['variant_aggregation']['per_task_pearson'].keys())
        agent_tasks = set(agent['variant_aggregation']['per_task_pearson'].keys())
        assert exp_tasks == agent_tasks, \
            f"VA task mismatch: expected {exp_tasks}, got {agent_tasks}"

    def test_vm_per_task_count(self, agent):
        n_tasks = len(agent['visual_matching']['per_task_pearson'])
        assert n_tasks == 7, f"Expected 7 tasks, got {n_tasks}"

    def test_vm_degenerate_task_is_null(self, agent):
        """A task with constant sim values must have null per-task correlation."""
        push = agent['visual_matching']['per_task_pearson'].get('push_buttons')
        assert push is None, \
            f"push_buttons VM per-task Pearson should be null (got {push})"

    def test_va_no_null_tasks(self, agent):
        """VA after weighted aggregation should have no null per-task correlations."""
        for task, val in agent['variant_aggregation']['per_task_pearson'].items():
            assert val is not None, f"VA per-task Pearson for {task} should not be null"

    def test_vm_per_task_values(self, agent, expected):
        for task, exp_r in expected['visual_matching']['per_task_pearson'].items():
            if exp_r is None:
                continue
            agent_r = agent['visual_matching']['per_task_pearson'][task]
            assert agent_r is not None, f"VM per-task Pearson for {task} should not be null"
            assert abs(agent_r - exp_r) < 0.05, \
                f"VM per-task Pearson for {task}: got {agent_r}, expected {exp_r}"

    def test_va_per_task_values(self, agent, expected):
        for task, exp_r in expected['variant_aggregation']['per_task_pearson'].items():
            agent_r = agent['variant_aggregation']['per_task_pearson'][task]
            assert abs(agent_r - exp_r) < 0.05, \
                f"VA per-task Pearson for {task}: got {agent_r}, expected {exp_r}"


# ---------------------------------------------------------------------------
# Fisher z-transform tests
# ---------------------------------------------------------------------------

class TestFisherZ:
    def test_vm_fisher_z(self, agent, expected):
        assert abs(agent['visual_matching']['fisher_z_mean_r'] - expected['visual_matching']['fisher_z_mean_r']) < 0.02, \
            f"VM Fisher z mean: got {agent['visual_matching']['fisher_z_mean_r']}, expected {expected['visual_matching']['fisher_z_mean_r']}"

    def test_va_fisher_z(self, agent, expected):
        assert abs(agent['variant_aggregation']['fisher_z_mean_r'] - expected['variant_aggregation']['fisher_z_mean_r']) < 0.02, \
            f"VA Fisher z mean: got {agent['variant_aggregation']['fisher_z_mean_r']}, expected {expected['variant_aggregation']['fisher_z_mean_r']}"

    def test_vm_fisher_z_excludes_null(self, agent):
        """Fisher z mean for VM should be computed over 6 tasks (excluding the null one)."""
        ptp = agent['visual_matching']['per_task_pearson']
        valid = [v for v in ptp.values() if v is not None]
        assert len(valid) == 6, f"Expected 6 valid per-task correlations for VM, got {len(valid)}"


# ---------------------------------------------------------------------------
# Bootstrap CI tests
# ---------------------------------------------------------------------------

class TestBootstrapCI:
    def test_vm_ci_ordered(self, agent):
        ci = agent['visual_matching']['pearson_r_ci_95']
        assert ci[0] < ci[1], f"CI lower ({ci[0]}) must be < CI upper ({ci[1]})"

    def test_va_ci_ordered(self, agent):
        ci = agent['variant_aggregation']['pearson_r_ci_95']
        assert ci[0] < ci[1], f"CI lower ({ci[0]}) must be < CI upper ({ci[1]})"

    def test_vm_ci_contains_point_estimate(self, agent):
        ci = agent['visual_matching']['pearson_r_ci_95']
        r = agent['visual_matching']['pearson_r']
        assert ci[0] <= r <= ci[1], \
            f"VM CI [{ci[0]}, {ci[1]}] should contain point estimate {r}"

    def test_va_ci_contains_point_estimate(self, agent):
        ci = agent['variant_aggregation']['pearson_r_ci_95']
        r = agent['variant_aggregation']['pearson_r']
        assert ci[0] <= r <= ci[1], \
            f"VA CI [{ci[0]}, {ci[1]}] should contain point estimate {r}"

    def test_vm_ci_lower(self, agent, expected):
        assert abs(agent['visual_matching']['pearson_r_ci_95'][0] - expected['visual_matching']['ci_lower']) < 0.03, \
            f"VM CI lower: got {agent['visual_matching']['pearson_r_ci_95'][0]}, expected {expected['visual_matching']['ci_lower']}"

    def test_vm_ci_upper(self, agent, expected):
        assert abs(agent['visual_matching']['pearson_r_ci_95'][1] - expected['visual_matching']['ci_upper']) < 0.03, \
            f"VM CI upper: got {agent['visual_matching']['pearson_r_ci_95'][1]}, expected {expected['visual_matching']['ci_upper']}"

    def test_va_ci_lower(self, agent, expected):
        assert abs(agent['variant_aggregation']['pearson_r_ci_95'][0] - expected['variant_aggregation']['ci_lower']) < 0.03, \
            f"VA CI lower: got {agent['variant_aggregation']['pearson_r_ci_95'][0]}, expected {expected['variant_aggregation']['ci_lower']}"

    def test_va_ci_upper(self, agent, expected):
        assert abs(agent['variant_aggregation']['pearson_r_ci_95'][1] - expected['variant_aggregation']['ci_upper']) < 0.03, \
            f"VA CI upper: got {agent['variant_aggregation']['pearson_r_ci_95'][1]}, expected {expected['variant_aggregation']['ci_upper']}"

    def test_ci_width_positive(self, agent):
        for approach in ['visual_matching', 'variant_aggregation']:
            ci = agent[approach]['pearson_r_ci_95']
            width = ci[1] - ci[0]
            assert width > 0.01, f"{approach} CI width ({width}) is suspiciously narrow"


# ---------------------------------------------------------------------------
# Comparison tests
# ---------------------------------------------------------------------------

class TestComparison:
    def test_better_approach_value(self, agent, expected):
        assert agent['comparison']['better_approach'] == expected['comparison']['better_approach'], \
            f"Better approach: got {agent['comparison']['better_approach']}, " \
            f"expected {expected['comparison']['better_approach']}"

    def test_better_approach_is_valid(self, agent):
        assert agent['comparison']['better_approach'] in ('visual_matching', 'variant_aggregation')

    def test_mmrv_difference(self, agent, expected):
        assert abs(agent['comparison']['mmrv_difference'] - expected['comparison']['mmrv_difference']) < 0.02, \
            f"MMRV diff: got {agent['comparison']['mmrv_difference']}, " \
            f"expected {expected['comparison']['mmrv_difference']}"

    def test_pearson_difference(self, agent, expected):
        assert abs(agent['comparison']['pearson_difference'] - expected['comparison']['pearson_difference']) < 0.02, \
            f"Pearson diff: got {agent['comparison']['pearson_difference']}, " \
            f"expected {expected['comparison']['pearson_difference']}"


# ---------------------------------------------------------------------------
# Data integrity tests (verify agent used correct data subset)
# ---------------------------------------------------------------------------

class TestDataIntegrity:
    def test_not_using_calibration_data(self, agent):
        """Verify the agent didn't include calibration experiment data.
        If calibration data were mixed in, the number of per-task entries would differ
        or the values would be off."""
        for approach in ['visual_matching', 'variant_aggregation']:
            ptp = agent[approach]['per_task_pearson']
            assert len(ptp) == 7, \
                f"{approach}: expected 7 tasks, got {len(ptp)} (possible calibration data leak)"

    def test_pearson_r_in_valid_range(self, agent):
        for approach in ['visual_matching', 'variant_aggregation']:
            r = agent[approach]['pearson_r']
            assert -1.0 <= r <= 1.0, f"{approach} Pearson r out of range: {r}"

    def test_nrmse_positive(self, agent):
        for approach in ['visual_matching', 'variant_aggregation']:
            assert agent[approach]['nrmse'] >= 0, \
                f"{approach} NRMSE should be non-negative"
