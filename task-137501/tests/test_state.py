"""Tests for conversion rate analysis pipeline.

Verifies the model produces correct, censoring-aware long-term conversion
estimates by testing on the provided dataset and on synthetic data with
known ground-truth parameters.
"""

import csv
import json
import math
import os
import random
import subprocess

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _run_model(input_csv, output_json, timeout=180):
    """Run the conversion_model package on given input."""
    result = subprocess.run(
        ['python3', '-m', 'conversion_model', input_csv, output_json],
        cwd='/app',
        capture_output=True,
        timeout=timeout,
    )
    assert result.returncode == 0, (
        f"conversion_model failed (exit {result.returncode}):\n"
        f"stdout: {result.stdout.decode()[:500]}\n"
        f"stderr: {result.stderr.decode()[:500]}"
    )


def _generate_synthetic(c, lam, p, n, max_obs, seed, path):
    """Generate synthetic right-censored conversion data with known params.

    Uses the inverse-CDF method: for a potential converter, sample
    T = (-ln(U))^(1/p) / lam.  If T > max_obs the observation is censored.
    A fraction (1-c) of users never convert.
    """
    rng = random.Random(seed)
    with open(path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'user_id', 'cohort_week', 'channel',
            'converted', 'days_to_event',
        ])
        for i in range(n):
            if rng.random() < c:
                u = rng.random()
                while u == 0:
                    u = rng.random()
                t = (-math.log(u)) ** (1.0 / p) / lam
                if t <= max_obs:
                    writer.writerow([i, '2024-W01', 'X', 1, round(t, 2)])
                else:
                    writer.writerow([i, '2024-W01', 'X', 0, max_obs])
            else:
                writer.writerow([i, '2024-W01', 'X', 0, max_obs])


def _naive_rate(csv_path, channel=None):
    """Compute the naive conversion rate (converted / total)."""
    total = converted = 0
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            if channel and row['channel'] != channel:
                continue
            total += 1
            if int(row['converted']) == 1:
                converted += 1
    return converted / total if total > 0 else 0


# ---------------------------------------------------------------------------
# 1. Results file exists and is loadable
# ---------------------------------------------------------------------------
class TestResultsExist:
    def test_results_json_exists(self):
        assert os.path.exists('/app/results.json'), \
            "/app/results.json not found"

    def test_results_loadable(self):
        with open('/app/results.json') as f:
            data = json.load(f)
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# 2. Output schema validation
# ---------------------------------------------------------------------------
class TestResultsSchema:
    @pytest.fixture(autouse=True)
    def load_results(self):
        with open('/app/results.json') as f:
            self.results = json.load(f)

    def test_channels_present(self):
        assert set(self.results.keys()) == {'A', 'B', 'C'}, \
            f"Expected channels A, B, C; got {set(self.results.keys())}"

    def test_required_keys(self):
        required = {
            'estimated_long_term_rate', 'ci_lower', 'ci_upper', 'model_type',
        }
        for ch in ('A', 'B', 'C'):
            missing = required - set(self.results[ch].keys())
            assert not missing, f"Channel {ch} missing keys: {missing}"

    def test_rate_in_unit_interval(self):
        for ch in ('A', 'B', 'C'):
            r = self.results[ch]['estimated_long_term_rate']
            assert 0 < r < 1, f"Channel {ch} rate {r} not in (0,1)"

    def test_ci_ordered(self):
        for ch in ('A', 'B', 'C'):
            lo = self.results[ch]['ci_lower']
            hi = self.results[ch]['ci_upper']
            assert 0 < lo < hi < 1, f"Channel {ch} CI [{lo}, {hi}] invalid"

    def test_ci_contains_estimate(self):
        for ch in ('A', 'B', 'C'):
            r = self.results[ch]
            assert r['ci_lower'] <= r['estimated_long_term_rate'] <= r['ci_upper'], \
                f"Channel {ch}: estimate {r['estimated_long_term_rate']} outside CI"

    def test_model_type_is_string(self):
        for ch in ('A', 'B', 'C'):
            mt = self.results[ch]['model_type']
            assert isinstance(mt, str) and len(mt) > 0


# ---------------------------------------------------------------------------
# 3. Estimate accuracy (ground-truth: A~0.35, B~0.25, C~0.45)
# ---------------------------------------------------------------------------
class TestEstimateAccuracy:
    @pytest.fixture(autouse=True)
    def load_results(self):
        with open('/app/results.json') as f:
            self.results = json.load(f)

    def test_channel_a_rate(self):
        est = self.results['A']['estimated_long_term_rate']
        assert 0.20 < est < 0.50, f"Channel A: expected ~0.35, got {est}"

    def test_channel_b_rate(self):
        est = self.results['B']['estimated_long_term_rate']
        assert 0.12 < est < 0.40, f"Channel B: expected ~0.25, got {est}"

    def test_channel_c_rate(self):
        est = self.results['C']['estimated_long_term_rate']
        assert 0.30 < est < 0.60, f"Channel C: expected ~0.45, got {est}"

    def test_channel_ordering_c_gt_b(self):
        """Channel C must have a higher long-term rate than channel B."""
        assert (
            self.results['C']['estimated_long_term_rate']
            > self.results['B']['estimated_long_term_rate']
        ), "Channel C should outperform B"

    def test_channel_ordering_a_between(self):
        """Channel A should be between B and C."""
        rates = {
            ch: self.results[ch]['estimated_long_term_rate'] for ch in 'ABC'
        }
        assert rates['B'] < rates['A'] < rates['C'], \
            f"Expected B < A < C, got B={rates['B']:.3f} A={rates['A']:.3f} C={rates['C']:.3f}"


# ---------------------------------------------------------------------------
# 4. Censoring awareness: estimates should differ from naive rates
# ---------------------------------------------------------------------------
class TestCensoringAwareness:
    def test_estimates_exceed_naive(self):
        """Censoring biases naive rates downward; the model should correct this."""
        with open('/app/results.json') as f:
            results = json.load(f)

        higher_count = 0
        for ch in ('A', 'B', 'C'):
            naive = _naive_rate('/app/data/conversions.csv', ch)
            estimated = results[ch]['estimated_long_term_rate']
            if estimated > naive * 1.05:
                higher_count += 1

        assert higher_count >= 2, \
            "Model should estimate higher rates than naive computation for most channels"

    def test_not_trivial_adjustment(self):
        """The correction from naive should be non-trivial for at least one channel."""
        with open('/app/results.json') as f:
            results = json.load(f)

        max_ratio = 0
        for ch in ('A', 'B', 'C'):
            naive = _naive_rate('/app/data/conversions.csv', ch)
            if naive > 0:
                ratio = results[ch]['estimated_long_term_rate'] / naive
                max_ratio = max(max_ratio, ratio)

        assert max_ratio > 1.10, \
            f"Max ratio est/naive = {max_ratio:.3f}; expected > 1.10 for censored data"


# ---------------------------------------------------------------------------
# 5. Confidence interval quality
# ---------------------------------------------------------------------------
class TestConfidenceIntervals:
    @pytest.fixture(autouse=True)
    def load_results(self):
        with open('/app/results.json') as f:
            self.results = json.load(f)

    def test_ci_width_not_degenerate(self):
        for ch in ('A', 'B', 'C'):
            width = self.results[ch]['ci_upper'] - self.results[ch]['ci_lower']
            assert width > 0.01, f"Channel {ch} CI too narrow: {width:.4f}"

    def test_ci_width_not_excessive(self):
        for ch in ('A', 'B', 'C'):
            width = self.results[ch]['ci_upper'] - self.results[ch]['ci_lower']
            assert width < 0.40, f"Channel {ch} CI too wide: {width:.4f}"


# ---------------------------------------------------------------------------
# 6. Module executable interface
# ---------------------------------------------------------------------------
class TestModuleInterface:
    def test_module_executes_on_main_data(self):
        """The package must be runnable as python3 -m conversion_model."""
        _run_model('/app/data/conversions.csv', '/tmp/test_module_out.json')
        assert os.path.exists('/tmp/test_module_out.json')
        with open('/tmp/test_module_out.json') as f:
            data = json.load(f)
        assert 'A' in data
        assert 'estimated_long_term_rate' in data['A']


# ---------------------------------------------------------------------------
# 7. Parameter recovery on synthetic data
# ---------------------------------------------------------------------------
class TestParameterRecovery:
    def test_recovery_moderate_ceiling(self):
        """Recover c ~ 0.6 from data with moderate censoring."""
        _generate_synthetic(0.6, 0.04, 1.2, 2500, 150, 42,
                            '/tmp/synth_mod.csv')
        _run_model('/tmp/synth_mod.csv', '/tmp/synth_mod_out.json')
        with open('/tmp/synth_mod_out.json') as f:
            out = json.load(f)
        est = out['X']['estimated_long_term_rate']
        assert 0.40 < est < 0.80, f"Expected ~0.6, got {est}"

    def test_recovery_low_ceiling(self):
        """Recover c ~ 0.15 from data with low conversion rate."""
        _generate_synthetic(0.15, 0.08, 1.0, 2500, 100, 99,
                            '/tmp/synth_low.csv')
        _run_model('/tmp/synth_low.csv', '/tmp/synth_low_out.json')
        with open('/tmp/synth_low_out.json') as f:
            out = json.load(f)
        est = out['X']['estimated_long_term_rate']
        assert 0.05 < est < 0.30, f"Expected ~0.15, got {est}"

    def test_recovery_heavy_censoring(self):
        """With short observation window, still recover substantially above naive rate.

        True c=0.5 but with max_obs=30, lam=0.02, p=1.5 the naive rate
        is ~0.19.  The model must extrapolate beyond observed data.
        """
        _generate_synthetic(0.5, 0.02, 1.5, 3000, 30, 77,
                            '/tmp/synth_heavy.csv')
        _run_model('/tmp/synth_heavy.csv', '/tmp/synth_heavy_out.json')
        with open('/tmp/synth_heavy_out.json') as f:
            out = json.load(f)
        est = out['X']['estimated_long_term_rate']
        # Naive rate is ~0.19; true rate is 0.5
        assert 0.25 < est < 0.80, f"Expected ~0.5, got {est}"

    def test_recovery_distinguishes_from_naive(self):
        """On heavily censored data the estimate must beat naive by >20%."""
        # Using the heavy-censoring data from previous test
        if not os.path.exists('/tmp/synth_heavy_out.json'):
            _generate_synthetic(0.5, 0.02, 1.5, 3000, 30, 77,
                                '/tmp/synth_heavy.csv')
            _run_model('/tmp/synth_heavy.csv', '/tmp/synth_heavy_out.json')
        naive = _naive_rate('/tmp/synth_heavy.csv', 'X')
        with open('/tmp/synth_heavy_out.json') as f:
            out = json.load(f)
        est = out['X']['estimated_long_term_rate']
        assert est > naive * 1.20, \
            f"Estimate {est:.3f} not sufficiently above naive {naive:.3f}"
