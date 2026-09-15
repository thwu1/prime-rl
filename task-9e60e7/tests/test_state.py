
import pytest
import json
import os


@pytest.fixture(scope="module")
def results():
    path = "/app/results.json"
    assert os.path.isfile(path), f"{path} does not exist"
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, dict), "results.json root must be a JSON object"
    return data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _mass(r):
    for k in ("fitted_mass_gev", "mass_gev", "mass"):
        if k in r:
            return float(r[k])
    return 0.0


def _yld(r):
    for k in ("yield", "signal_yield", "n_signal"):
        if k in r:
            return r[k]
    return 0


def _sig(r):
    for k in ("significance_sigma", "significance", "sig"):
        if k in r:
            return float(r[k])
    return 0.0


def _width(r):
    for k in ("fitted_width_gev", "width_gev", "fwhm_gev", "width"):
        if k in r:
            return float(r[k])
    return 0.0


def _find_in_range(results, lo, hi):
    for r in results["resonances"]:
        m = _mass(r)
        if lo <= m <= hi:
            return r
    return None


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------
class TestStructure:
    def test_has_validation(self, results):
        assert "validation" in results, "Missing 'validation' key"

    def test_has_resonances(self, results):
        assert "resonances" in results, "Missing 'resonances' key"
        assert isinstance(results["resonances"], list)

    def test_has_yield_ratios(self, results):
        assert "yield_ratios" in results, "Missing 'yield_ratios' key"
        assert isinstance(results["yield_ratios"], dict)


# ---------------------------------------------------------------------------
# Invariant-mass validation
# ---------------------------------------------------------------------------
class TestValidation:
    def test_mass_deviation_small(self, results):
        v = results["validation"]
        assert "mass_recomputation_max_deviation_gev" in v
        dev = v["mass_recomputation_max_deviation_gev"]
        assert dev < 0.5, f"Mass recomputation deviation {dev:.6f} >= 0.5 GeV"

    def test_total_events_reasonable(self, results):
        total = results["validation"]["total_events"]
        assert 90000 < total < 110000, f"Expected ~100k events, got {total}"

    def test_selection_reduces_events(self, results):
        v = results["validation"]
        assert v["selected_events"] < v["total_events"], (
            "Event selection should reduce the sample"
        )

    def test_selected_events_positive(self, results):
        assert results["validation"]["selected_events"] > 0


# ---------------------------------------------------------------------------
# Resonance identification
# ---------------------------------------------------------------------------
class TestResonances:
    """Verify that the pipeline identifies the major dimuon resonances."""

    # --- count ---
    def test_at_least_5_resonances(self, results):
        n = len(results["resonances"])
        assert n >= 5, f"Found only {n} resonances, need >= 5"

    # --- J/psi ---
    def test_jpsi_found(self, results):
        r = _find_in_range(results, 3.0, 3.2)
        assert r is not None, "No resonance in J/psi range [3.0, 3.2] GeV"

    # --- psi(2S) ---
    def test_psi_prime_found(self, results):
        r = _find_in_range(results, 3.5, 3.9)
        assert r is not None, "No resonance in psi(2S) range [3.5, 3.9] GeV"

    # --- Upsilon region ---
    def test_upsilon_found(self, results):
        r = _find_in_range(results, 9.0, 10.6)
        assert r is not None, "No resonance in Upsilon range [9.0, 10.6] GeV"

    # --- Z ---
    def test_z_found(self, results):
        r = _find_in_range(results, 88.0, 94.0)
        assert r is not None, "No resonance in Z range [88, 94] GeV"

    # --- field presence ---
    def test_each_resonance_has_name(self, results):
        for i, r in enumerate(results["resonances"]):
            assert "name" in r and len(str(r["name"])) > 0, (
                f"Resonance index {i} missing 'name'"
            )

    def test_each_resonance_has_mass(self, results):
        for i, r in enumerate(results["resonances"]):
            m = _mass(r)
            assert m > 0, f"Resonance {r.get('name','?')} has no valid mass"

    # --- physics sanity ---
    def test_all_yields_positive(self, results):
        for r in results["resonances"]:
            y = _yld(r)
            assert y > 0, (
                f"Resonance {r.get('name','?')} yield={y} is not positive"
            )

    def test_all_significances_positive(self, results):
        for r in results["resonances"]:
            s = _sig(r)
            assert s > 0, (
                f"Resonance {r.get('name','?')} significance={s} is not positive"
            )

    def test_no_duplicate_resonances(self, results):
        masses = sorted(_mass(r) for r in results["resonances"])
        for i in range(len(masses) - 1):
            gap = masses[i + 1] - masses[i]
            assert gap > 0.1, (
                f"Two resonances too close: {masses[i]:.3f} and "
                f"{masses[i+1]:.3f} GeV (gap {gap:.3f})"
            )

    def test_jpsi_yield_greater_than_upsilon(self, results):
        """J/psi is produced far more copiously than Upsilon(1S)."""
        jpsi = _find_in_range(results, 3.0, 3.2)
        ups = _find_in_range(results, 9.0, 10.0)
        if jpsi is not None and ups is not None:
            y_jpsi = _yld(jpsi)
            y_ups = _yld(ups)
            assert y_jpsi > y_ups, (
                f"J/psi yield ({y_jpsi}) should exceed Upsilon(1S) yield ({y_ups})"
            )


# ---------------------------------------------------------------------------
# Physics consistency — width and significance
# ---------------------------------------------------------------------------
class TestPhysicsConsistency:
    """Expert-level physics cross-checks on fitted resonance parameters."""

    def test_z_broader_than_jpsi(self, results):
        """The Z boson has a natural width of ~2.5 GeV (dominates detector
        resolution), while J/psi is narrow (~93 keV natural, detector-limited).
        The fitted FWHM must reflect this hierarchy."""
        jpsi = _find_in_range(results, 3.0, 3.2)
        z = _find_in_range(results, 88.0, 94.0)
        if jpsi is not None and z is not None:
            w_jpsi = _width(jpsi)
            w_z = _width(z)
            assert w_z > w_jpsi, (
                f"Z width ({w_z:.3f} GeV) must exceed J/psi width "
                f"({w_jpsi:.3f} GeV) — fundamental width hierarchy"
            )

    def test_discovery_significance(self, results):
        """At least one resonance must exceed the conventional 5-sigma
        discovery threshold used in particle physics."""
        sigs = [_sig(r) for r in results["resonances"]]
        assert max(sigs) > 5.0, (
            f"Highest significance {max(sigs):.1f}σ is below the 5σ threshold"
        )

    def test_spectrum_spans_quarkonium_and_ew(self, results):
        """The spectrum must contain resonances at both the quarkonium scale
        (< 12 GeV) and the electroweak scale (> 50 GeV)."""
        masses = sorted(_mass(r) for r in results["resonances"])
        assert masses[0] < 5.0, (
            f"Lowest resonance at {masses[0]:.1f} GeV — "
            "expected quarkonium below 5 GeV"
        )
        assert masses[-1] > 50.0, (
            f"Highest resonance at {masses[-1]:.1f} GeV — "
            "expected electroweak boson above 50 GeV"
        )

    def test_jpsi_width_sub_gev(self, results):
        """J/psi is intrinsically narrow (93 keV); even with detector
        smearing the observed FWHM should be well below 1 GeV."""
        jpsi = _find_in_range(results, 3.0, 3.2)
        if jpsi is not None:
            w = _width(jpsi)
            assert 0 < w < 1.0, (
                f"J/psi fitted FWHM {w:.3f} GeV is outside (0, 1) GeV"
            )


# ---------------------------------------------------------------------------
# Yield ratios
# ---------------------------------------------------------------------------
class TestYieldRatios:
    def test_at_least_two_ratios(self, results):
        ratios = results.get("yield_ratios", {})
        assert len(ratios) >= 2, f"Expected >= 2 yield ratios, got {len(ratios)}"

    def test_all_ratios_positive(self, results):
        for key, val in results.get("yield_ratios", {}).items():
            assert val > 0, f"Yield ratio '{key}' = {val} is not positive"
