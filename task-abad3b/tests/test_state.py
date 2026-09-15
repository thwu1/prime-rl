
import json
import os
import math
import pytest

CATALOG_PATH = "/app/resonance_catalog.json"
SUMMARY_PATH = "/app/analysis_summary.json"

# Known PDG masses (GeV)
PDG = {
    "rho_omega": 0.775,
    "phi": 1.019,
    "J_psi": 3.097,
    "psi_prime": 3.686,
    "Upsilon_1S": 9.460,
    "Upsilon_2S": 10.023,
    "Upsilon_3S": 10.355,
    "Z": 91.188,
}


def load_catalog():
    assert os.path.isfile(CATALOG_PATH), f"{CATALOG_PATH} not found"
    with open(CATALOG_PATH) as f:
        data = json.load(f)
    assert "resonances" in data, "Missing 'resonances' key in catalog"
    return data["resonances"]


def load_summary():
    assert os.path.isfile(SUMMARY_PATH), f"{SUMMARY_PATH} not found"
    with open(SUMMARY_PATH) as f:
        return json.load(f)


# ---- Structural tests ----

class TestCatalogStructure:
    def test_catalog_file_exists(self):
        assert os.path.isfile(CATALOG_PATH)

    def test_catalog_valid_json(self):
        with open(CATALOG_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)
        assert "resonances" in data

    def test_resonances_is_list(self):
        resonances = load_catalog()
        assert isinstance(resonances, list)

    def test_at_least_five_resonances(self):
        resonances = load_catalog()
        assert len(resonances) >= 5, (
            f"Expected >= 5 resonances, found {len(resonances)}"
        )

    def test_each_resonance_has_required_fields(self):
        required = [
            "name", "measured_mass_gev", "fitted_width_gev",
            "signal_yield", "significance_sigma",
            "pdg_mass_gev", "mass_residual_pct",
        ]
        for r in load_catalog():
            for field in required:
                assert field in r, f"Missing field '{field}' in resonance {r}"


# ---- Physics accuracy tests ----

class TestPhysicsAccuracy:
    def _find_resonance_near(self, target_mass, tol_frac=0.05):
        """Return the resonance closest to target_mass if within tol_frac."""
        resonances = load_catalog()
        best = None
        best_diff = float("inf")
        for r in resonances:
            diff = abs(r["measured_mass_gev"] - target_mass) / target_mass
            if diff < best_diff:
                best_diff = diff
                best = r
        assert best is not None and best_diff < tol_frac, (
            f"No resonance found within {tol_frac*100}% of {target_mass} GeV. "
            f"Closest: {best}"
        )
        return best

    def test_jpsi_detected(self):
        """J/psi must be found near 3.097 GeV."""
        r = self._find_resonance_near(3.097, 0.05)
        assert r["measured_mass_gev"] > 0

    def test_upsilon1s_detected(self):
        """Upsilon(1S) must be found near 9.460 GeV."""
        r = self._find_resonance_near(9.460, 0.05)
        assert r["measured_mass_gev"] > 0

    def test_z_boson_detected(self):
        """Z boson must be found near 91.188 GeV."""
        r = self._find_resonance_near(91.188, 0.05)
        assert r["measured_mass_gev"] > 0

    def test_all_masses_near_known_particles(self):
        """Every detected resonance must be within 15% of a known PDG mass."""
        resonances = load_catalog()
        pdg_masses = list(PDG.values())
        for r in resonances:
            m = r["measured_mass_gev"]
            min_frac_diff = min(abs(m - p) / p for p in pdg_masses)
            assert min_frac_diff < 0.15, (
                f"Resonance at {m:.3f} GeV does not match any known particle "
                f"(closest fractional diff: {min_frac_diff:.3f})"
            )

    def test_positive_yields(self):
        for r in load_catalog():
            assert r["signal_yield"] > 0, (
                f"Non-positive yield for {r.get('name', '?')}"
            )

    def test_positive_significance(self):
        for r in load_catalog():
            assert r["significance_sigma"] > 0, (
                f"Non-positive significance for {r.get('name', '?')}"
            )

    def test_positive_widths(self):
        for r in load_catalog():
            assert r["fitted_width_gev"] > 0, (
                f"Non-positive width for {r.get('name', '?')}"
            )


# ---- Data integrity tests ----

class TestDataIntegrity:
    def test_summary_file_exists(self):
        assert os.path.isfile(SUMMARY_PATH)

    def test_total_events(self):
        s = load_summary()
        assert "total_events" in s
        assert s["total_events"] == 50000, (
            f"Expected 50000 total events, got {s['total_events']}"
        )

    def test_events_after_cuts_reasonable(self):
        s = load_summary()
        assert "events_after_quality_cuts" in s
        n = s["events_after_quality_cuts"]
        assert 5000 < n < 49500, (
            f"events_after_quality_cuts={n} is outside plausible range"
        )

    def test_nan_events_detected(self):
        s = load_summary()
        assert "events_with_nan_dropped" in s
        n = s["events_with_nan_dropped"]
        assert 50 < n < 1000, (
            f"events_with_nan_dropped={n} is outside expected range"
        )

    def test_mass_recomputation_accuracy(self):
        s = load_summary()
        assert "mass_validation_max_abs_diff" in s
        d = s["mass_validation_max_abs_diff"]
        assert d < 0.01, (
            f"mass_validation_max_abs_diff={d} exceeds 0.01 GeV tolerance "
            f"(invariant mass recomputation may be incorrect)"
        )

    def test_mass_recomputation_mean(self):
        s = load_summary()
        assert "mass_validation_mean_abs_diff" in s
        d = s["mass_validation_mean_abs_diff"]
        assert d < 0.001, (
            f"mass_validation_mean_abs_diff={d} exceeds 0.001 GeV tolerance"
        )
