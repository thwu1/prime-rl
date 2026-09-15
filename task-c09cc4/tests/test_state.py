
import hashlib
import json
import os
import pytest
import numpy as np
from scipy.optimize import minimize_scalar
from scipy.integrate import quad
from scipy.special import gamma
from scipy.stats import weibull_min

# Use /opt/task_data/ as the authoritative config path (survives volume mounts).
# Fall back to /app/config.json if the opt path is missing.
CONFIG_PATH = '/opt/task_data/config.json' if os.path.exists('/opt/task_data/config.json') else '/app/config.json'
RESULTS_PATH = '/app/results.json'


@pytest.fixture(scope='module')
def config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


@pytest.fixture(scope='module')
def results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


@pytest.fixture(scope='module')
def scenarios(config):
    return {s['name']: s for s in config['scenarios']}


# ---------------------------------------------------------------------------
# Reference computation helpers
# ---------------------------------------------------------------------------

def compute_system_params(scenario):
    """Compute Weibull parameters and MTBF for the system-level failure distribution."""
    N = scenario['num_workers']
    mtbf_worker_sec = scenario['failure_model']['mtbf_hours_per_worker'] * 3600.0
    k = scenario['failure_model'].get('shape', 1.0)

    lam_worker = mtbf_worker_sec / gamma(1.0 + 1.0 / k)
    lam_sys = lam_worker * N ** (-1.0 / k)
    mtbf_sys = lam_sys * gamma(1.0 + 1.0 / k)
    return k, lam_sys, mtbf_sys


def ref_expected_complete(tau, k, lam_sys, R):
    """Expected wall-clock time to complete one interval of duration tau."""
    S_tau = np.exp(-(tau / lam_sys) ** k)
    if S_tau > 1.0 - 1e-15:
        return tau
    F_tau = 1.0 - S_tau
    integral, _ = quad(
        lambda x: x * weibull_min.pdf(x, k, scale=lam_sys), 0, tau,
        limit=200
    )
    E_trunc = integral / F_tau
    return (1.0 / S_tau - 1.0) * (E_trunc + R) + tau


def ref_expected_total(delta, W, C, k, lam_sys, R):
    """Expected total time with periodic checkpointing every delta seconds."""
    if delta <= 0:
        return float('inf')
    n_full = int(W // delta)
    W_remain = W - n_full * delta

    total = 0.0
    if n_full > 0:
        total += n_full * ref_expected_complete(delta + C, k, lam_sys, R)
    if W_remain > 1e-10:
        total += ref_expected_complete(W_remain, k, lam_sys, R)
    return total


def ref_optimal_interval(W, C, R, k, lam_sys, iter_time):
    """Find optimal checkpoint interval via bounded minimization."""
    result = minimize_scalar(
        lambda d: ref_expected_total(d, W, C, k, lam_sys, R),
        bounds=(iter_time, W),
        method='bounded',
        options={'xatol': 0.01}
    )
    return result.x


def get_ref_values(scenario):
    """Compute all reference values for a scenario."""
    k, lam_sys, mtbf_sys = compute_system_params(scenario)
    iter_time = scenario['iteration_time_sec']
    W = scenario['total_iterations'] * iter_time
    C = scenario['checkpoint_cost_sec']
    R = scenario['recovery_cost_sec']

    delta_opt = ref_optimal_interval(W, C, R, k, lam_sys, iter_time)
    delta_opt_iter = max(1, round(delta_opt / iter_time))
    delta_opt_aligned = delta_opt_iter * iter_time

    delta_fixed = scenario['fixed_checkpoint_interval_iter'] * iter_time

    E_no = ref_expected_complete(W, k, lam_sys, R)
    E_opt = ref_expected_total(delta_opt_aligned, W, C, k, lam_sys, R)
    E_fixed = ref_expected_total(delta_fixed, W, C, k, lam_sys, R)
    E_zero = ref_expected_total(iter_time, W, 0, k, lam_sys, R)

    return {
        'k': k, 'lam_sys': lam_sys, 'mtbf_sys': mtbf_sys,
        'W': W, 'C': C, 'R': R, 'iter_time': iter_time,
        'delta_opt': delta_opt, 'delta_opt_aligned': delta_opt_aligned,
        'delta_fixed': delta_fixed,
        'E_no': E_no, 'E_opt': E_opt, 'E_fixed': E_fixed, 'E_zero': E_zero,
        'delta_opt_iter': delta_opt_iter,
    }


def compute_verification_digest(config, scenario_refs):
    """Compute the expected verification digest from DNA + computed values."""
    dna = config['task_dna']
    parts = [dna]
    for sc in config['scenarios']:
        ref = scenario_refs[sc['name']]
        parts.append(f"{ref['mtbf_sys']:.2f}")
        parts.append(str(ref['delta_opt_iter']))
    digest_input = "|".join(parts)
    return hashlib.sha256(digest_input.encode()).hexdigest()


# ---------------------------------------------------------------------------
# DNA and structure tests
# ---------------------------------------------------------------------------

class TestDNA:
    def test_task_dna_present(self, results, config):
        """Results must echo the task_dna from config."""
        assert 'task_dna' in results, "Missing task_dna in results"
        assert results['task_dna'] == config['task_dna'], \
            f"task_dna mismatch: expected {config['task_dna']}, got {results['task_dna']}"

    def test_verification_digest_present(self, results):
        """Results must include a verification_digest."""
        assert 'verification_digest' in results, "Missing verification_digest in results"
        assert len(results['verification_digest']) == 64, \
            "verification_digest must be a 64-char SHA-256 hex string"

    def test_verification_digest_correct(self, results, config, scenarios):
        """The verification digest must match independently computed values."""
        scenario_refs = {}
        for sc in config['scenarios']:
            scenario_refs[sc['name']] = get_ref_values(sc)

        dna = config['task_dna']

        # First verify the submitted digest matches what would be computed
        # from the submitted values
        submitted_parts = [dna]
        for sc in config['scenarios']:
            r = results['scenarios'][sc['name']]
            submitted_parts.append(f"{r['system_mtbf_sec']:.2f}")
            submitted_parts.append(str(r['optimal_checkpoint_interval_iter']))
        submitted_input = "|".join(submitted_parts)
        submitted_digest = hashlib.sha256(submitted_input.encode()).hexdigest()
        assert results['verification_digest'] == submitted_digest, \
            "verification_digest does not match SHA-256 of submitted values"

        # Then verify the submitted values are close enough to reference
        # that the reference digest also matches
        ref_digest = compute_verification_digest(config, scenario_refs)
        assert results['verification_digest'] == ref_digest, \
            f"verification_digest mismatch: submitted values diverge from reference.\n" \
            f"Expected digest: {ref_digest}\nGot: {results['verification_digest']}"


class TestResultsStructure:
    def test_results_file_exists(self, results):
        assert 'scenarios' in results

    def test_scenario_names(self, results, config):
        for s in config['scenarios']:
            assert s['name'] in results['scenarios'], \
                f"Missing scenario {s['name']} in results"

    def test_scenario_fields(self, results, config):
        for s in config['scenarios']:
            r = results['scenarios'][s['name']]
            assert 'system_mtbf_sec' in r
            assert 'optimal_checkpoint_interval_sec' in r
            assert 'optimal_checkpoint_interval_iter' in r
            assert 'expected_time' in r
            assert 'overhead_ratio' in r
            assert 'monte_carlo' in r

            for key in ['no_checkpoint_sec', 'optimal_periodic_sec',
                        'fixed_periodic_sec', 'zero_cost_per_iter_sec']:
                assert key in r['expected_time'], f"Missing {key} in expected_time"

            for key in ['no_checkpoint', 'optimal_periodic',
                        'fixed_periodic', 'zero_cost_per_iter']:
                assert key in r['overhead_ratio'], f"Missing {key} in overhead_ratio"
                assert key in r['monte_carlo'], f"Missing {key} in monte_carlo"
                mc = r['monte_carlo'][key]
                for field in ['mean', 'std', 'ci_lower', 'ci_upper']:
                    assert field in mc, f"Missing {field} in monte_carlo.{key}"


# ---------------------------------------------------------------------------
# Parameterized per-scenario tests
# ---------------------------------------------------------------------------

SCENARIO_NAMES = ['exponential_baseline', 'weibull_aging', 'mixed_fleet']


@pytest.mark.parametrize('scenario_name', SCENARIO_NAMES)
class TestScenarioAnalytical:

    def test_system_mtbf(self, scenarios, results, scenario_name):
        sc = scenarios[scenario_name]
        ref = get_ref_values(sc)
        sr = results['scenarios'][scenario_name]
        assert abs(sr['system_mtbf_sec'] - ref['mtbf_sys']) / ref['mtbf_sys'] < 0.001, \
            f"MTBF mismatch: expected {ref['mtbf_sys']:.2f}, got {sr['system_mtbf_sec']:.2f}"

    def test_optimal_interval(self, scenarios, results, scenario_name):
        sc = scenarios[scenario_name]
        ref = get_ref_values(sc)
        sr = results['scenarios'][scenario_name]
        reported = sr['optimal_checkpoint_interval_sec']
        assert abs(reported - ref['delta_opt_aligned']) / ref['delta_opt_aligned'] < 0.15, \
            f"Optimal interval mismatch: expected {ref['delta_opt_aligned']:.2f}, got {reported:.2f}"

    def test_optimal_interval_is_near_minimum(self, scenarios, results, scenario_name):
        sc = scenarios[scenario_name]
        ref = get_ref_values(sc)
        sr = results['scenarios'][scenario_name]
        ref_min = ref_expected_total(
            ref['delta_opt_aligned'], ref['W'], ref['C'],
            ref['k'], ref['lam_sys'], ref['R']
        )
        reported_et = sr['expected_time']['optimal_periodic_sec']
        assert reported_et / ref_min < 1.05, \
            f"Optimal expected time {reported_et:.1f} too far from minimum {ref_min:.1f}"

    def test_optimal_periodic_expected_time(self, scenarios, results, scenario_name):
        sc = scenarios[scenario_name]
        sr = results['scenarios'][scenario_name]
        k, lam_sys, _ = compute_system_params(sc)
        W = sc['total_iterations'] * sc['iteration_time_sec']
        C = sc['checkpoint_cost_sec']
        R = sc['recovery_cost_sec']
        reported_delta = sr['optimal_checkpoint_interval_sec']
        ref_et = ref_expected_total(reported_delta, W, C, k, lam_sys, R)
        assert abs(sr['expected_time']['optimal_periodic_sec'] - ref_et) / ref_et < 0.05

    def test_no_checkpoint_expected_time(self, scenarios, results, scenario_name):
        sc = scenarios[scenario_name]
        ref = get_ref_values(sc)
        sr = results['scenarios'][scenario_name]
        assert abs(sr['expected_time']['no_checkpoint_sec'] - ref['E_no']) / ref['E_no'] < 0.05

    def test_fixed_periodic_expected_time(self, scenarios, results, scenario_name):
        sc = scenarios[scenario_name]
        ref = get_ref_values(sc)
        sr = results['scenarios'][scenario_name]
        assert abs(sr['expected_time']['fixed_periodic_sec'] - ref['E_fixed']) / ref['E_fixed'] < 0.05

    def test_zero_cost_expected_time(self, scenarios, results, scenario_name):
        sc = scenarios[scenario_name]
        ref = get_ref_values(sc)
        sr = results['scenarios'][scenario_name]
        assert abs(sr['expected_time']['zero_cost_per_iter_sec'] - ref['E_zero']) / ref['E_zero'] < 0.05

    def test_strategy_ordering(self, results, scenario_name):
        et = results['scenarios'][scenario_name]['expected_time']
        assert et['zero_cost_per_iter_sec'] < et['optimal_periodic_sec']
        assert et['optimal_periodic_sec'] <= et['fixed_periodic_sec'] * 1.02
        assert et['fixed_periodic_sec'] < et['no_checkpoint_sec']

    def test_overhead_ratios_consistency(self, scenarios, results, scenario_name):
        sc = scenarios[scenario_name]
        sr = results['scenarios'][scenario_name]
        base = sc['total_iterations'] * sc['iteration_time_sec']
        et_map = {
            'no_checkpoint': 'no_checkpoint_sec',
            'optimal_periodic': 'optimal_periodic_sec',
            'fixed_periodic': 'fixed_periodic_sec',
            'zero_cost_per_iter': 'zero_cost_per_iter_sec',
        }
        for key, et_key in et_map.items():
            expected = (sr['expected_time'][et_key] - base) / base
            reported = sr['overhead_ratio'][key]
            assert abs(reported - expected) < 0.01, \
                f"Overhead ratio for {key}: expected {expected:.4f}, got {reported:.4f}"

    def test_overhead_ordering(self, results, scenario_name):
        o = results['scenarios'][scenario_name]['overhead_ratio']
        assert o['zero_cost_per_iter'] < o['optimal_periodic']
        assert o['optimal_periodic'] < o['no_checkpoint']
        for v in o.values():
            assert v >= 0


# ---------------------------------------------------------------------------
# Weibull shape-specific tests
# ---------------------------------------------------------------------------

class TestWeibullShapeEffects:
    @pytest.mark.parametrize('scenario_name', ['weibull_aging', 'mixed_fleet'])
    def test_weibull_shape_gt_1(self, scenarios, results, scenario_name):
        """With k > 1, MTBF_sys = MTBF_worker * N^(-1/k) > MTBF_worker / N."""
        sc = scenarios[scenario_name]
        sr = results['scenarios'][scenario_name]
        N = sc['num_workers']
        mtbf_w = sc['failure_model']['mtbf_hours_per_worker'] * 3600.0
        k = sc['failure_model']['shape']
        assert k > 1.0
        lower_bound = mtbf_w / N
        assert sr['system_mtbf_sec'] > lower_bound

    def test_mixed_fleet_more_workers_lower_mtbf(self, scenarios, results):
        """mixed_fleet (23 workers, k=1.55) should have lower MTBF than weibull_aging (19 workers, k=1.85)."""
        sr_mixed = results['scenarios']['mixed_fleet']
        sr_weibull = results['scenarios']['weibull_aging']
        assert sr_mixed['system_mtbf_sec'] < sr_weibull['system_mtbf_sec']

    def test_exponential_mtbf_formula(self, scenarios, results):
        """For exponential (k=1), MTBF_sys = MTBF_worker / N exactly."""
        sc = scenarios['exponential_baseline']
        sr = results['scenarios']['exponential_baseline']
        N = sc['num_workers']
        mtbf_w = sc['failure_model']['mtbf_hours_per_worker'] * 3600.0
        expected = mtbf_w / N
        assert abs(sr['system_mtbf_sec'] - expected) / expected < 0.001


# ---------------------------------------------------------------------------
# Monte Carlo tests
# ---------------------------------------------------------------------------

class TestMonteCarlo:
    @pytest.mark.parametrize('scenario_name', SCENARIO_NAMES)
    def test_mc_within_tolerance(self, results, scenario_name):
        """MC mean should be within 20% of analytical for each strategy."""
        r = results['scenarios'][scenario_name]
        strategies = [
            ('no_checkpoint', 'no_checkpoint_sec'),
            ('optimal_periodic', 'optimal_periodic_sec'),
            ('fixed_periodic', 'fixed_periodic_sec'),
            ('zero_cost_per_iter', 'zero_cost_per_iter_sec'),
        ]
        for mc_key, et_key in strategies:
            analytical = r['expected_time'][et_key]
            mc_mean = r['monte_carlo'][mc_key]['mean']
            rel_error = abs(mc_mean - analytical) / analytical
            assert rel_error < 0.20, \
                f"{scenario_name}/{mc_key}: MC mean={mc_mean:.1f} vs analytical={analytical:.1f} (err={rel_error:.3f})"

    @pytest.mark.parametrize('scenario_name', SCENARIO_NAMES)
    def test_mc_ci_valid(self, results, scenario_name):
        """CI lower < mean < CI upper, and std > 0."""
        r = results['scenarios'][scenario_name]
        for key in ['no_checkpoint', 'optimal_periodic', 'fixed_periodic', 'zero_cost_per_iter']:
            mc = r['monte_carlo'][key]
            assert mc['ci_lower'] < mc['mean'] < mc['ci_upper'], \
                f"{scenario_name}/{key}: invalid CI [{mc['ci_lower']}, {mc['ci_upper']}] for mean {mc['mean']}"
            assert mc['std'] > 0, f"{scenario_name}/{key}: std must be positive"

    @pytest.mark.parametrize('scenario_name', SCENARIO_NAMES)
    def test_mc_cv_reasonable(self, results, scenario_name):
        """Coefficient of variation should be < 2 for all strategies."""
        r = results['scenarios'][scenario_name]
        for key in ['no_checkpoint', 'optimal_periodic', 'fixed_periodic', 'zero_cost_per_iter']:
            mc = r['monte_carlo'][key]
            cv = mc['std'] / mc['mean']
            assert cv < 2.0, f"{scenario_name}/{key}: CV={cv:.2f} is too large"

    @pytest.mark.parametrize('scenario_name', SCENARIO_NAMES)
    def test_mc_ordering(self, results, scenario_name):
        """MC means should roughly follow the same ordering as analytical."""
        r = results['scenarios'][scenario_name]
        mc = r['monte_carlo']
        assert mc['zero_cost_per_iter']['mean'] < mc['no_checkpoint']['mean']
