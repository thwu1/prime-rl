
import pytest
import numpy as np
import json
import ast
import os
from math import gamma, log


# Ground-truth generating parameters (not visible to the agent)
TRUE = {
    'station_A': {'xi': 0.2, 'sigma': 10.0, 'mu': 50.0,
                  'family': 'frechet', 'contaminated': False},
    'station_B': {'xi': 0.0, 'sigma': 8.0, 'mu': 25.0,
                  'family': 'gumbel', 'contaminated': False},
    'station_C': {'xi': -0.15, 'sigma': 5.0, 'mu': 100.0,
                  'family': 'weibull', 'contaminated': False},
    'station_D': {'xi': 0.1, 'sigma': 7.0, 'mu': 40.0,
                  'family': 'frechet', 'contaminated': True},
    'station_E': {'xi': -0.2, 'sigma': 6.0, 'mu': 80.0,
                  'family': 'weibull', 'contaminated': True},
}

STATIONS = list(TRUE.keys())
CLEAN = [s for s in STATIONS if not TRUE[s]['contaminated']]
CONTAMINATED = [s for s in STATIONS if TRUE[s]['contaminated']]


def gev_return_level(xi, sigma, mu, T):
    """Reference GEV return level computation."""
    p = 1 - 1.0 / T
    if abs(xi) < 1e-10:
        return mu - sigma * log(-log(p))
    return mu + sigma * ((-log(p)) ** (-xi) - 1) / xi


@pytest.fixture(scope="module")
def report():
    with open('/app/report.json') as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Report structure
# ---------------------------------------------------------------------------

class TestReportStructure:
    def test_report_exists(self):
        assert os.path.exists('/app/report.json'), \
            "report.json not found at /app/report.json"

    def test_all_stations_present(self, report):
        for name in STATIONS:
            assert name in report, f"Missing {name} in report"

    def test_required_fields(self, report):
        fields = ['family', 'params', 'return_levels',
                  'contaminated', 'suspect_fraction']
        for name in STATIONS:
            for f in fields:
                assert f in report[name], \
                    f"Missing field '{f}' in {name}"

    def test_params_keys(self, report):
        for name in STATIONS:
            for k in ['xi', 'sigma', 'mu']:
                assert k in report[name]['params'], \
                    f"Missing 'params.{k}' in {name}"

    def test_return_level_keys(self, report):
        for name in STATIONS:
            for k in ['T100', 'T500']:
                assert k in report[name]['return_levels'], \
                    f"Missing 'return_levels.{k}' in {name}"


# ---------------------------------------------------------------------------
# Family classification
# ---------------------------------------------------------------------------

class TestFamilyClassification:
    @pytest.mark.parametrize("name", STATIONS)
    def test_family_correct(self, name, report):
        expected = TRUE[name]['family']
        actual = report[name]['family']
        assert actual == expected, \
            f"{name}: expected family '{expected}', got '{actual}'"


# ---------------------------------------------------------------------------
# Parameter accuracy
# ---------------------------------------------------------------------------

class TestParameterAccuracy:
    @pytest.mark.parametrize("name", STATIONS)
    def test_xi_accuracy(self, name, report):
        true_xi = TRUE[name]['xi']
        est_xi = report[name]['params']['xi']
        tol = 0.12 if TRUE[name]['contaminated'] else 0.08
        assert abs(est_xi - true_xi) < tol, \
            f"{name}: xi={est_xi:.4f}, true={true_xi}, " \
            f"|diff|={abs(est_xi - true_xi):.4f}, tol={tol}"

    @pytest.mark.parametrize("name", STATIONS)
    def test_sigma_accuracy(self, name, report):
        true_sigma = TRUE[name]['sigma']
        est_sigma = report[name]['params']['sigma']
        rel_err = abs(est_sigma - true_sigma) / true_sigma
        tol = 0.30 if TRUE[name]['contaminated'] else 0.25
        assert rel_err < tol, \
            f"{name}: sigma={est_sigma:.4f}, true={true_sigma}, " \
            f"rel_err={rel_err:.4f}, tol={tol}"

    @pytest.mark.parametrize("name", STATIONS)
    def test_mu_accuracy(self, name, report):
        true_mu = TRUE[name]['mu']
        est_mu = report[name]['params']['mu']
        abs_tol = max(0.10 * abs(true_mu), 8) if TRUE[name]['contaminated'] \
            else max(0.08 * abs(true_mu), 5)
        assert abs(est_mu - true_mu) < abs_tol, \
            f"{name}: mu={est_mu:.4f}, true={true_mu}, " \
            f"|diff|={abs(est_mu - true_mu):.4f}, tol={abs_tol}"

    @pytest.mark.parametrize("name", STATIONS)
    def test_sigma_positive(self, name, report):
        assert report[name]['params']['sigma'] > 0, \
            f"{name}: sigma must be positive"


# ---------------------------------------------------------------------------
# Contamination detection
# ---------------------------------------------------------------------------

class TestContaminationDetection:
    @pytest.mark.parametrize("name", CONTAMINATED)
    def test_contaminated_detected(self, name, report):
        assert report[name]['contaminated'] is True, \
            f"{name} should be flagged as contaminated"

    @pytest.mark.parametrize("name", CLEAN)
    def test_clean_not_flagged(self, name, report):
        assert report[name]['contaminated'] is False, \
            f"{name} should NOT be flagged as contaminated"

    @pytest.mark.parametrize("name", CONTAMINATED)
    def test_suspect_fraction_positive(self, name, report):
        sf = report[name]['suspect_fraction']
        assert sf > 0.005, \
            f"{name}: suspect_fraction={sf}, expected > 0.005"

    @pytest.mark.parametrize("name", CONTAMINATED)
    def test_suspect_fraction_bounded(self, name, report):
        sf = report[name]['suspect_fraction']
        assert sf < 0.20, \
            f"{name}: suspect_fraction={sf} too high"

    @pytest.mark.parametrize("name", CLEAN)
    def test_clean_suspect_fraction_low(self, name, report):
        sf = report[name]['suspect_fraction']
        assert sf < 0.03, \
            f"{name}: suspect_fraction={sf}, expected < 0.03 for clean data"


# ---------------------------------------------------------------------------
# Return levels
# ---------------------------------------------------------------------------

class TestReturnLevels:
    @pytest.mark.parametrize("name", STATIONS)
    def test_return_level_consistency(self, name, report):
        """Return levels must be consistent with reported GEV parameters."""
        xi = report[name]['params']['xi']
        sigma = report[name]['params']['sigma']
        mu = report[name]['params']['mu']

        for T_str, T in [('T100', 100), ('T500', 500)]:
            expected = gev_return_level(xi, sigma, mu, T)
            actual = report[name]['return_levels'][T_str]
            np.testing.assert_allclose(
                actual, expected, rtol=1e-3,
                err_msg=f"{name} {T_str}: {actual:.4f} vs {expected:.4f}")

    @pytest.mark.parametrize("name", STATIONS)
    def test_return_level_ordering(self, name, report):
        rl100 = report[name]['return_levels']['T100']
        rl500 = report[name]['return_levels']['T500']
        assert rl500 > rl100, \
            f"{name}: T500 ({rl500}) should exceed T100 ({rl100})"


# ---------------------------------------------------------------------------
# Code integrity — no banned libraries
# ---------------------------------------------------------------------------

class TestCodeIntegrity:
    def test_no_banned_imports(self):
        """Implementation must not use pre-built EV or L-moment libraries."""
        banned = {'lmo', 'lmoments3', 'lmoments', 'pyextremes'}

        for root, dirs, files in os.walk('/app'):
            for fname in files:
                if not fname.endswith('.py'):
                    continue
                fpath = os.path.join(root, fname)
                with open(fpath) as f:
                    try:
                        tree = ast.parse(f.read())
                    except SyntaxError:
                        continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            base = alias.name.split('.')[0]
                            assert base not in banned, \
                                f"Banned import '{alias.name}' in {fpath}"
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            base = node.module.split('.')[0]
                            assert base not in banned, \
                                f"Banned import from '{node.module}' in {fpath}"

    def test_no_genextreme(self):
        """Must not use scipy.stats.genextreme."""
        for root, dirs, files in os.walk('/app'):
            for fname in files:
                if not fname.endswith('.py'):
                    continue
                fpath = os.path.join(root, fname)
                with open(fpath) as f:
                    content = f.read()
                assert 'genextreme' not in content, \
                    f"Use of genextreme detected in {fpath}"
