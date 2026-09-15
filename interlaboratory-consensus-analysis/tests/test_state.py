"""

Tests for interlaboratory consensus analysis tool.
Independently verifies deterministic quantities and checks stochastic outputs
for structural correctness and consistency.
"""

import pytest
import json
import os
import numpy as np
from scipy import stats


# ---- Independent reference computation ----

def dl_reference(x, u):
    """Compute DL consensus, tau-squared, Q, I-squared from raw data."""
    n = len(x)
    w0 = 1.0 / u**2
    x0 = np.sum(w0 * x) / np.sum(w0)
    Q = np.sum(w0 * (x - x0)**2)
    c = np.sum(w0) - np.sum(w0**2) / np.sum(w0)
    tau2 = max(0.0, (Q - (n - 1)) / c)
    w = 1.0 / (u**2 + tau2)
    mu = np.sum(w * x) / np.sum(w)
    I2 = max(0.0, (Q - (n - 1)) / Q * 100.0) if Q > 0 else 0.0
    return mu, tau2, Q, I2


def hksj_reference(x, u, mu, tau2, coverage=0.95):
    """Compute modified HKSJ 95% CI from raw data."""
    n = len(x)
    w = 1.0 / (u**2 + tau2)
    q = np.sum(w * (x - mu)**2) / (n - 1)
    qstar = max(1.0, q)
    se = np.sqrt(qstar / np.sum(w))
    df = n - 1
    t_upper = stats.t.ppf((1 + coverage) / 2, df)
    t_lower = stats.t.ppf((1 - coverage) / 2, df)
    ci_upper = mu + np.sqrt(qstar) * se * t_upper
    ci_lower = mu + np.sqrt(qstar) * se * t_lower
    return ci_lower, ci_upper


# ---- Dataset definitions ----

PCB28_X = np.array([34.30, 32.90, 34.53, 32.42, 31.90, 35.80])
PCB28_U = np.array([1.03, 0.69, 0.83, 0.29, 0.40, 0.38])
PCB28_LABS = ['IRMM', 'KRISS', 'NARL', 'NIST', 'NMIJ', 'NRC']

GAUGE_X = np.array([15.0, 15.0, 30.0, 18.0, 24.0, -9.0, 33.0, 12.5, 8.8])
GAUGE_U = np.array([9.0, 14.0, 10.0, 13.0, 9.0, 7.0, 9.0, 8.6, 10.0])
GAUGE_LABS = ['OFMET', 'NPL', 'LNE', 'NRC', 'NIST', 'CENAM', 'CSIRO', 'NRLM', 'KRISS']

RADIO_X = np.array([7077, 7065, 7056, 7047, 7051, 7060, 7090, 7053, 7037,
                     7099, 7057, 7098, 7050, 7040, 7050, 7039, 7101, 7083, 7057],
                    dtype=float)
RADIO_U = np.array([8, 26, 10, 22, 18, 4, 11, 21, 8, 46, 16, 16, 15, 40, 8,
                     17, 24, 14, 17], dtype=float)
RADIO_LABS = ['LNMRI', 'ENEA', 'ANSTO', 'KRISS', 'MKEH', 'LNE-LNHB',
              'CIEMAT', 'NPL', 'IRA', 'BARC', 'PTB', 'NMISA', 'CNEA',
              'RC', 'NMIJ', 'IRMM', 'IFIN-HH', 'NIST', 'BEV']


def load_results(name):
    path = f'/app/results/{name}.json'
    assert os.path.isfile(path), f"Missing results file: {path}"
    with open(path) as f:
        return json.load(f)


# ---- Test: results files exist with required keys ----

class TestResultsExist:
    REQUIRED_KEYS = ['consensus_dl', 'tau_squared', 'tau', 'cochran_q',
                     'i_squared', 'hksj_ci', 'consensus_lp', 'doe']

    @pytest.mark.parametrize("name", ["pcb28", "gauge_blocks", "radionuclide"])
    def test_file_exists(self, name):
        assert os.path.isfile(f'/app/results/{name}.json')

    @pytest.mark.parametrize("name", ["pcb28", "gauge_blocks", "radionuclide"])
    def test_required_keys(self, name):
        r = load_results(name)
        for key in self.REQUIRED_KEYS:
            assert key in r, f"Missing key '{key}' in {name}.json"


# ---- Test: PCB-28 dataset ----

class TestPCB28:
    def setup_method(self):
        self.results = load_results("pcb28")
        self.mu, self.tau2, self.Q, self.I2 = dl_reference(PCB28_X, PCB28_U)

    def test_dl_consensus(self):
        assert abs(self.results['consensus_dl'] - self.mu) < 0.01

    def test_tau_squared(self):
        assert abs(self.results['tau_squared'] - self.tau2) < 0.01

    def test_tau(self):
        assert abs(self.results['tau'] - np.sqrt(self.tau2)) < 0.01

    def test_cochran_q(self):
        assert abs(self.results['cochran_q'] - self.Q) < 0.1

    def test_i_squared(self):
        assert abs(self.results['i_squared'] - self.I2) < 0.5

    def test_hksj_ci(self):
        ci_lo, ci_hi = hksj_reference(PCB28_X, PCB28_U, self.mu, self.tau2)
        assert abs(self.results['hksj_ci'][0] - ci_lo) < 0.05
        assert abs(self.results['hksj_ci'][1] - ci_hi) < 0.05

    def test_hksj_ci_contains_consensus(self):
        assert self.results['hksj_ci'][0] < self.results['consensus_dl']
        assert self.results['hksj_ci'][1] > self.results['consensus_dl']

    def test_lp_consensus_reasonable(self):
        unweighted = float(np.mean(PCB28_X))
        assert abs(self.results['consensus_lp'] - unweighted) < 1.5

    def test_doe_structure(self):
        doe = self.results['doe']
        assert len(doe) == 6
        for lab in PCB28_LABS:
            assert lab in doe
            assert 'value' in doe[lab]
            assert 'U95' in doe[lab]
            assert 'significant' in doe[lab]

    def test_doe_values_match_deterministic(self):
        doe = self.results['doe']
        for j, lab in enumerate(PCB28_LABS):
            expected = float(PCB28_X[j] - self.mu)
            assert abs(doe[lab]['value'] - expected) < 0.01, \
                f"{lab}: DoE value {doe[lab]['value']:.4f} != expected {expected:.4f}"

    def test_doe_u95_positive(self):
        for lab, d in self.results['doe'].items():
            assert d['U95'] > 0, f"{lab}: U95 must be positive"

    def test_doe_significance_consistency(self):
        for lab, d in self.results['doe'].items():
            expected_sig = abs(d['value']) > d['U95']
            assert d['significant'] == expected_sig, \
                f"{lab}: significant={d['significant']} but |value|={abs(d['value']):.4f}, U95={d['U95']:.4f}"

    def test_high_heterogeneity(self):
        """PCB-28 should show high heterogeneity."""
        assert self.results['i_squared'] > 80.0


# ---- Test: Gauge blocks dataset ----

class TestGaugeBlocks:
    def setup_method(self):
        self.results = load_results("gauge_blocks")
        self.mu, self.tau2, self.Q, self.I2 = dl_reference(GAUGE_X, GAUGE_U)

    def test_dl_consensus(self):
        assert abs(self.results['consensus_dl'] - self.mu) < 0.1

    def test_tau_squared(self):
        assert abs(self.results['tau_squared'] - self.tau2) < 1.0

    def test_tau(self):
        assert abs(self.results['tau'] - np.sqrt(self.tau2)) < 0.5

    def test_cochran_q(self):
        assert abs(self.results['cochran_q'] - self.Q) < 0.5

    def test_i_squared(self):
        assert abs(self.results['i_squared'] - self.I2) < 1.0

    def test_hksj_ci(self):
        ci_lo, ci_hi = hksj_reference(GAUGE_X, GAUGE_U, self.mu, self.tau2)
        assert abs(self.results['hksj_ci'][0] - ci_lo) < 1.0
        assert abs(self.results['hksj_ci'][1] - ci_hi) < 1.0

    def test_hksj_ci_contains_consensus(self):
        assert self.results['hksj_ci'][0] < self.results['consensus_dl']
        assert self.results['hksj_ci'][1] > self.results['consensus_dl']

    def test_lp_reasonable(self):
        unweighted = float(np.mean(GAUGE_X))
        assert abs(self.results['consensus_lp'] - unweighted) < 5.0

    def test_doe_structure(self):
        doe = self.results['doe']
        assert len(doe) == 9
        for lab in GAUGE_LABS:
            assert lab in doe, f"Missing lab {lab} in DoE"

    def test_doe_values_match_deterministic(self):
        doe = self.results['doe']
        for j, lab in enumerate(GAUGE_LABS):
            expected = float(GAUGE_X[j] - self.mu)
            assert abs(doe[lab]['value'] - expected) < 0.1

    def test_doe_significance_consistency(self):
        for lab, d in self.results['doe'].items():
            expected_sig = abs(d['value']) > d['U95']
            assert d['significant'] == expected_sig

    def test_dark_uncertainty_positive(self):
        assert self.results['tau_squared'] > 0
        assert self.results['tau'] > 0


# ---- Test: Radionuclide dataset ----

class TestRadionuclide:
    def setup_method(self):
        self.results = load_results("radionuclide")
        self.mu, self.tau2, self.Q, self.I2 = dl_reference(RADIO_X, RADIO_U)

    def test_dl_consensus(self):
        assert abs(self.results['consensus_dl'] - self.mu) < 0.5

    def test_tau_squared(self):
        assert abs(self.results['tau_squared'] - self.tau2) < 5.0

    def test_tau(self):
        assert abs(self.results['tau'] - np.sqrt(self.tau2)) < 1.0

    def test_cochran_q(self):
        assert abs(self.results['cochran_q'] - self.Q) < 1.0

    def test_i_squared(self):
        assert abs(self.results['i_squared'] - self.I2) < 1.0

    def test_hksj_ci(self):
        ci_lo, ci_hi = hksj_reference(RADIO_X, RADIO_U, self.mu, self.tau2)
        assert abs(self.results['hksj_ci'][0] - ci_lo) < 1.0
        assert abs(self.results['hksj_ci'][1] - ci_hi) < 1.0

    def test_hksj_ci_contains_consensus(self):
        assert self.results['hksj_ci'][0] < self.results['consensus_dl']
        assert self.results['hksj_ci'][1] > self.results['consensus_dl']

    def test_heterogeneity_detected(self):
        assert self.results['i_squared'] > 50.0

    def test_dark_uncertainty_positive(self):
        assert self.results['tau_squared'] > 0
        assert self.results['tau'] > 0

    def test_doe_structure(self):
        doe = self.results['doe']
        assert len(doe) == 19
        for lab in RADIO_LABS:
            assert lab in doe, f"Missing lab {lab} in DoE"

    def test_doe_values_match_deterministic(self):
        doe = self.results['doe']
        for j, lab in enumerate(RADIO_LABS):
            expected = float(RADIO_X[j] - self.mu)
            assert abs(doe[lab]['value'] - expected) < 0.5

    def test_doe_significance_consistency(self):
        for lab, d in self.results['doe'].items():
            expected_sig = abs(d['value']) > d['U95']
            assert d['significant'] == expected_sig

    def test_no_df_handling(self):
        """Dataset without df column must still produce valid LP and DoE."""
        assert self.results['consensus_lp'] is not None
        lp = self.results['consensus_lp']
        assert 7020 < lp < 7110

    def test_lp_near_unweighted(self):
        unweighted = float(np.mean(RADIO_X))
        assert abs(self.results['consensus_lp'] - unweighted) < 5.0


# ---- Test: Cross-dataset consistency ----

class TestCrossDataset:
    def test_ci_contains_consensus(self):
        for name in ["pcb28", "gauge_blocks", "radionuclide"]:
            r = load_results(name)
            assert r['hksj_ci'][0] < r['consensus_dl'] < r['hksj_ci'][1], \
                f"{name}: CI [{r['hksj_ci'][0]:.2f}, {r['hksj_ci'][1]:.2f}] " \
                f"does not contain consensus {r['consensus_dl']:.2f}"

    def test_tau_consistency(self):
        for name in ["pcb28", "gauge_blocks", "radionuclide"]:
            r = load_results(name)
            assert abs(r['tau'] - np.sqrt(r['tau_squared'])) < 1e-6, \
                f"{name}: tau={r['tau']:.6f} != sqrt(tau_squared)={np.sqrt(r['tau_squared']):.6f}"

    def test_i_squared_range(self):
        for name in ["pcb28", "gauge_blocks", "radionuclide"]:
            r = load_results(name)
            assert 0 <= r['i_squared'] <= 100, \
                f"{name}: I-squared={r['i_squared']} out of [0,100] range"

    def test_lp_near_dl(self):
        """LP and DL consensus should be in the same ballpark."""
        for name in ["pcb28", "gauge_blocks", "radionuclide"]:
            r = load_results(name)
            tau = r['tau']
            diff = abs(r['consensus_lp'] - r['consensus_dl'])
            bound = max(3 * tau, 5.0)
            assert diff < bound, \
                f"{name}: |LP-DL|={diff:.2f} exceeds 3*tau={3*tau:.2f}"

    def test_hksj_ci_is_interval(self):
        for name in ["pcb28", "gauge_blocks", "radionuclide"]:
            r = load_results(name)
            assert r['hksj_ci'][0] < r['hksj_ci'][1], \
                f"{name}: CI lower >= upper"

    def test_doe_all_u95_positive(self):
        for name in ["pcb28", "gauge_blocks", "radionuclide"]:
            r = load_results(name)
            for lab, d in r['doe'].items():
                assert d['U95'] > 0, f"{name}/{lab}: U95 must be positive"
