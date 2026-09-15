
import json
import subprocess
import shutil
import glob as glob_module
import numpy as np
from math import comb
import pytest


TRUE_PARAMS = {
    "site_alpha": {"loc": 15.0, "scale": 4.0, "shape": -0.1},
    "site_beta": {"loc": 10.0, "scale": 3.5, "shape": -0.15},
    "site_gamma": {"loc": 25.0, "scale": 6.0, "shape": -0.2},
}

CONTAMINATED_SITES = {"site_beta"}
CLEAN_SITES = {"site_alpha", "site_gamma"}


def compute_reference_lmoments(data, nmom=4):
    """Compute reference L-moments using probability weighted moments (PWMs)."""
    x = np.sort(data)
    n = len(x)
    b = np.zeros(nmom)
    for r in range(nmom):
        cn = comb(n - 1, r)
        for i in range(r, n):
            b[r] += comb(i, r) * x[i] / cn
        b[r] /= n
    lmom = np.zeros(nmom)
    for r in range(1, nmom + 1):
        for k in range(r):
            p = (-1) ** (r - 1 - k) * comb(r - 1, k) * comb(r - 1 + k, k)
            lmom[r - 1] += p * b[k]
    return lmom


def compute_reference_tlmoments(data, s=1, t=1, nmom=4):
    """Compute reference TL-moments using Elamir-Seheult (2003) formula."""
    x = np.sort(data)
    n = len(x)
    tlmom = []
    for r in range(1, nmom + 1):
        denom = comb(n, r + s + t)
        total = 0.0
        for i in range(n):
            weight = 0
            for k in range(r):
                c1 = (-1) ** k * comb(r - 1, k)
                c2 = comb(i, r + s - 1 - k)
                c3 = comb(n - 1 - i, t + k)
                weight += c1 * c2 * c3
            total += weight * x[i]
        total /= (r * denom)
        tlmom.append(float(total))
    return tlmom


def get_site_data(results, site_name):
    """Extract site data, handling optional nested 'sites' key."""
    sites = results.get('sites', results)
    return sites[site_name]


class TestResultsStructure:
    """Verify results.json has all required fields for all sites."""

    @classmethod
    def setup_class(cls):
        with open('/app/results.json', 'r') as f:
            cls.results = json.load(f)

    def test_all_sites_present(self):
        sites = self.results.get('sites', self.results)
        for name in TRUE_PARAMS:
            assert name in sites, f"Missing site: {name}"

    def test_required_fields_per_site(self):
        sites = self.results.get('sites', self.results)
        for name in TRUE_PARAMS:
            site = sites[name]
            for key in ['lmoments', 'tlmoments', 'lratios', 'tlratios', 'gev_params']:
                assert key in site, f"Missing '{key}' in {name}"
            assert len(site['lmoments']) == 4, f"{name}: lmoments needs 4 elements"
            assert len(site['tlmoments']) == 4, f"{name}: tlmoments needs 4 elements"
            assert len(site['lratios']) == 2, f"{name}: lratios needs 2 elements"
            assert len(site['tlratios']) == 2, f"{name}: tlratios needs 2 elements"
            for p in ['loc', 'scale', 'shape']:
                assert p in site['gev_params'], f"Missing gev_params.{p} in {name}"

    def test_gev_params_finite_and_valid(self):
        sites = self.results.get('sites', self.results)
        for name in TRUE_PARAMS:
            params = sites[name]['gev_params']
            for p in ['loc', 'scale', 'shape']:
                assert np.isfinite(params[p]), f"{name}.{p} not finite: {params[p]}"
            assert params['scale'] > 0, f"{name}.scale must be positive: {params['scale']}"


class TestSiteBetaDiagnostics:
    """Verify site_beta contamination is diagnosed and robust estimation applied."""

    @classmethod
    def setup_class(cls):
        with open('/app/results.json', 'r') as f:
            raw = json.load(f)
        cls.site = get_site_data(raw, 'site_beta')
        cls.data = np.load('/app/data/raw/site_beta.npy')

    def test_lmoments_accuracy(self):
        ref = compute_reference_lmoments(self.data)
        agent = np.array(self.site['lmoments'])
        for i in range(4):
            rel_err = abs(agent[i] - ref[i]) / (abs(ref[i]) + 1e-10)
            assert rel_err < 0.01, \
                f"site_beta L-moment {i+1}: expected {ref[i]:.6f}, got {agent[i]:.6f} (rel_err={rel_err:.4f})"

    def test_tlmoments_accuracy(self):
        ref = compute_reference_tlmoments(self.data, s=1, t=1)
        agent = np.array(self.site['tlmoments'])
        for i in range(4):
            rel_err = abs(agent[i] - ref[i]) / (abs(ref[i]) + 1e-10)
            assert rel_err < 0.01, \
                f"site_beta TL-moment {i+1}: expected {ref[i]:.6f}, got {agent[i]:.6f} (rel_err={rel_err:.4f})"

    def test_lratios_consistency(self):
        lmom = np.array(self.site['lmoments'])
        lratios = np.array(self.site['lratios'])
        assert abs(lratios[0] - lmom[2] / lmom[1]) < 1e-6, \
            f"tau3 inconsistent: {lratios[0]:.6f} vs {lmom[2]/lmom[1]:.6f}"
        assert abs(lratios[1] - lmom[3] / lmom[1]) < 1e-6, \
            f"tau4 inconsistent: {lratios[1]:.6f} vs {lmom[3]/lmom[1]:.6f}"

    def test_tlratios_consistency(self):
        tlmom = np.array(self.site['tlmoments'])
        tlratios = np.array(self.site['tlratios'])
        assert abs(tlratios[0] - tlmom[2] / tlmom[1]) < 1e-6, \
            f"TL tau3 inconsistent: {tlratios[0]:.6f} vs {tlmom[2]/tlmom[1]:.6f}"
        assert abs(tlratios[1] - tlmom[3] / tlmom[1]) < 1e-6, \
            f"TL tau4 inconsistent: {tlratios[1]:.6f} vs {tlmom[3]/tlmom[1]:.6f}"

    def test_gev_shape_accuracy(self):
        shape = self.site['gev_params']['shape']
        true = TRUE_PARAMS['site_beta']['shape']
        assert abs(shape - true) < 0.15, \
            f"site_beta shape: expected ~{true}, got {shape:.4f}"

    def test_gev_scale_accuracy(self):
        scale = self.site['gev_params']['scale']
        true = TRUE_PARAMS['site_beta']['scale']
        rel_err = abs(scale - true) / true
        assert rel_err < 0.25, \
            f"site_beta scale: expected ~{true}, got {scale:.4f} (rel_err={rel_err:.4f})"

    def test_gev_loc_accuracy(self):
        loc = self.site['gev_params']['loc']
        true = TRUE_PARAMS['site_beta']['loc']
        rel_err = abs(loc - true) / true
        assert rel_err < 0.25, \
            f"site_beta loc: expected ~{true}, got {loc:.4f} (rel_err={rel_err:.4f})"

    def test_contamination_flagged(self):
        quality = self.site.get('data_quality', '').lower()
        assert 'contam' in quality, \
            f"site_beta should be flagged as contaminated, got: '{quality}'"

    def test_robust_method_selected(self):
        method = self.site.get('estimation_method', '').lower()
        assert 'tl' in method, \
            f"site_beta should use TL-moment estimation, got: '{method}'"


class TestCleanSites:
    """Verify clean sites have correct estimates and quality flags."""

    @classmethod
    def setup_class(cls):
        with open('/app/results.json', 'r') as f:
            raw = json.load(f)
        cls.sites = raw.get('sites', raw)

    @pytest.mark.parametrize("name", ["site_alpha", "site_gamma"])
    def test_gev_shape(self, name):
        shape = self.sites[name]['gev_params']['shape']
        true = TRUE_PARAMS[name]['shape']
        assert abs(shape - true) < 0.15, \
            f"{name} shape: expected ~{true}, got {shape:.4f}"

    @pytest.mark.parametrize("name", ["site_alpha", "site_gamma"])
    def test_gev_scale(self, name):
        scale = self.sites[name]['gev_params']['scale']
        true = TRUE_PARAMS[name]['scale']
        rel_err = abs(scale - true) / true
        assert rel_err < 0.25, \
            f"{name} scale: expected ~{true}, got {scale:.4f} (rel_err={rel_err:.4f})"

    @pytest.mark.parametrize("name", ["site_alpha", "site_gamma"])
    def test_gev_loc(self, name):
        loc = self.sites[name]['gev_params']['loc']
        true = TRUE_PARAMS[name]['loc']
        rel_err = abs(loc - true) / true
        assert rel_err < 0.25, \
            f"{name} loc: expected ~{true}, got {loc:.4f} (rel_err={rel_err:.4f})"

    @pytest.mark.parametrize("name", ["site_alpha", "site_gamma"])
    def test_lmoments_accuracy(self, name):
        data = np.load(f'/app/data/raw/{name}.npy')
        ref = compute_reference_lmoments(data)
        agent = np.array(self.sites[name]['lmoments'])
        for i in range(4):
            rel_err = abs(agent[i] - ref[i]) / (abs(ref[i]) + 1e-10)
            assert rel_err < 0.01, \
                f"{name} L-moment {i+1}: expected {ref[i]:.6f}, got {agent[i]:.6f}"

    @pytest.mark.parametrize("name", ["site_alpha", "site_gamma"])
    def test_clean_quality_flag(self, name):
        quality = self.sites[name].get('data_quality', '').lower()
        assert 'clean' in quality, \
            f"{name} should be flagged as clean, got: '{quality}'"


class TestGeneralization:
    """Anti-hardcoding: re-run on modified data and verify results change."""

    def test_rerun_on_modified_data(self):
        from scipy.stats import genextreme

        scripts = glob_module.glob('/app/*.py')
        if not scripts:
            pytest.fail("No Python script found in /app/")
        script = '/app/analysis.py' if '/app/analysis.py' in scripts else scripts[0]

        # Backup originals
        shutil.copy('/app/data/raw/site_beta.npy', '/tmp/site_beta_backup.npy')
        shutil.copy('/app/results.json', '/tmp/results_backup.json')

        try:
            # Generate fresh contaminated data with DIFFERENT GEV parameters
            rng = np.random.default_rng(77777)
            fresh_shape = -0.18
            fresh_loc = 12.0
            fresh_scale = 4.0
            fresh_gev = genextreme.rvs(fresh_shape, loc=fresh_loc, scale=fresh_scale,
                                        size=2950, random_state=rng)
            cauchy = rng.standard_cauchy(size=50)
            cauchy = np.clip(cauchy, -30, 30)
            contamination = 70.0 + 12.0 * cauchy
            fresh_data = np.concatenate([fresh_gev, contamination])
            rng.shuffle(fresh_data)
            np.save('/app/data/raw/site_beta.npy', fresh_data)

            result = subprocess.run(
                ['python3', script], capture_output=True, text=True, timeout=300
            )
            assert result.returncode == 0, \
                f"Script failed on modified data: {result.stderr[:500]}"

            with open('/app/results.json', 'r') as f:
                fresh_results = json.load(f)

            beta = get_site_data(fresh_results, 'site_beta')

            # Verify L-moments match reference for fresh data
            ref_lmom = compute_reference_lmoments(fresh_data)
            agent_lmom = np.array(beta['lmoments'])
            for i in range(4):
                rel_err = abs(agent_lmom[i] - ref_lmom[i]) / (abs(ref_lmom[i]) + 1e-10)
                assert rel_err < 0.01, \
                    f"Fresh L-moment {i+1}: expected {ref_lmom[i]:.6f}, got {agent_lmom[i]:.6f}"

            # Verify GEV shape recovered on fresh data
            shape = beta['gev_params']['shape']
            assert abs(shape - fresh_shape) < 0.15, \
                f"Fresh shape: expected ~{fresh_shape}, got {shape:.4f}"

        finally:
            shutil.move('/tmp/site_beta_backup.npy', '/app/data/raw/site_beta.npy')
            shutil.move('/tmp/results_backup.json', '/app/results.json')
