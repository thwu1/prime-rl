"""
Tests for variable-coefficient ground-coupled slab heat transfer solver.
Verifies against analytical Fourier cosine series (homogeneous cases),
transfer-matrix series (layered soil), and physical consistency bounds
(insulation cases).

"""
import json
import math
import os

import pytest


# ---------------------------------------------------------------------------
# Analytical reference solutions
# ---------------------------------------------------------------------------

def analytical_heat_loss_homogeneous(B, w, W, D, k, delta_T, N_terms=50000):
    """
    Fourier cosine series solution for homogeneous-soil slab heat loss.

    Eigenfunctions cos(lambda_n x) with lambda_n = (2n+1)*pi/(2W) satisfy
    d(theta)/dx=0 at x=0 and theta=0 at x=W. The Fourier coefficients of
    the piecewise-linear top BC are integrated analytically, and the
    resulting series converges to the exact Q within machine precision at
    50000 terms.
    """
    Q_sum = 0.0
    Bpw = B + w
    Bpw2 = B + w / 2.0
    w2 = w / 2.0
    two_W = 2.0 * W

    for n in range(N_terms):
        lam = (2 * n + 1) * math.pi / two_W
        s1 = math.sin(lam * Bpw2)
        s2 = math.sin(lam * w2)
        s3 = math.sin(lam * Bpw)
        arg = lam * D
        if arg > 500.0:
            coth_val = 1.0
        elif arg < 1e-12:
            coth_val = 1.0 / arg
        else:
            coth_val = math.cosh(arg) / math.sinh(arg)
        Q_sum += s1 * s2 * s3 * coth_val / (lam * lam)

    return 8.0 * k * delta_T * Q_sum / (W * w)


def analytical_heat_loss_layered(B, w, W, d1, k1, k2, D, delta_T, N_terms=50000):
    """
    Transfer-matrix series solution for 2-layer soil.

    Layer 1: conductivity k1 from z=0 to z=d1.
    Layer 2: conductivity k2 from z=d1 to z=D.

    The eigenfunction expansion is the same as the homogeneous case, but the
    z-dependent amplitudes satisfy continuity of theta and k*d(theta)/dz at
    the layer interface. This yields a mode-dependent transfer factor R_n
    that replaces coth(lambda_n * D) in the homogeneous formula.
    """
    Q_sum = 0.0
    Bpw = B + w
    Bpw2 = B + w / 2.0
    w2 = w / 2.0
    two_W = 2.0 * W
    d2 = D - d1

    for n in range(N_terms):
        lam = (2 * n + 1) * math.pi / two_W
        L1 = lam * d1
        L2 = lam * d2

        s1 = math.sin(lam * Bpw2)
        s2 = math.sin(lam * w2)
        s3 = math.sin(lam * Bpw)

        # Overflow protection: when L1 or L2 is large, sinh/cosh overflow.
        # For large L1, sinh(L1) ~ cosh(L1) ~ exp(L1)/2, so R_n -> 1.
        if L1 > 500.0:
            R_n = 1.0
        else:
            if L2 > 500.0:
                coth_L2 = 1.0
            elif L2 < 1e-12:
                coth_L2 = 1.0 / L2
            else:
                coth_L2 = math.cosh(L2) / math.sinh(L2)

            numer = k1 * math.sinh(L1) + k2 * math.cosh(L1) * coth_L2
            denom = k1 * math.cosh(L1) + k2 * math.sinh(L1) * coth_L2

            R_n = numer / denom if abs(denom) > 1e-30 else 1.0

        Q_sum += s1 * s2 * s3 * R_n / (lam * lam)

    return 8.0 * k1 * delta_T * Q_sum / (W * w)


def compute_U_1d(soil_layers, D):
    """1D thermal transmittance through a vertical soil column."""
    R = 0.0
    prev_depth = 0.0
    for layer in soil_layers:
        d = min(layer["depth_to"], D) - prev_depth
        if d > 0:
            R += d / layer["conductivity"]
        prev_depth = layer["depth_to"]
        if prev_depth >= D:
            break
    return 1.0 / R if R > 0 else float("inf")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def load_results():
    path = "/app/results.json"
    assert os.path.exists(path), f"Results file not found at {path}"
    with open(path) as f:
        return json.load(f)


def load_cases():
    with open("/app/cases.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def results():
    return load_results()


@pytest.fixture(scope="module")
def cases():
    return load_cases()


@pytest.fixture(scope="module")
def reference_values(cases):
    """Compute analytical reference heat loss and psi for verifiable cases."""
    refs = {}
    for name, cfg in cases.items():
        if not isinstance(cfg, dict) or "slab_half_width" not in cfg:
            continue
        B = cfg["slab_half_width"]
        w = cfg["wall_thickness"]
        W = cfg["domain_width"]
        D = cfg["domain_depth"]
        dT = cfg["T_indoor"] - cfg["T_outdoor"]
        layers = cfg["soil_layers"]

        if len(layers) == 1 and "insulation" not in cfg:
            k = layers[0]["conductivity"]
            Q = analytical_heat_loss_homogeneous(B, w, W, D, k, dT)
        elif len(layers) == 2 and "insulation" not in cfg:
            d1 = layers[0]["depth_to"]
            k1 = layers[0]["conductivity"]
            k2 = layers[1]["conductivity"]
            Q = analytical_heat_loss_layered(B, w, W, d1, k1, k2, D, dT)
        else:
            Q = None

        U_1d = compute_U_1d(layers, D)
        psi = (Q / dT - U_1d * 2.0 * B) if Q is not None else None

        refs[name] = {"Q": Q, "U_1d": U_1d, "psi": psi}

    return refs


# ---------------------------------------------------------------------------
# All case names
# ---------------------------------------------------------------------------

ALL_CASES = [
    "GC_BASE", "GC_NARROW", "GC_WIDE", "GC_HIGHK", "GC_SHALLOW",
    "GC_LAYER", "GC_VINSUL", "GC_COMBO",
]

HOMOGENEOUS_CASES = ["GC_BASE", "GC_NARROW", "GC_WIDE", "GC_HIGHK", "GC_SHALLOW"]


# ---------------------------------------------------------------------------
# Format and structural tests
# ---------------------------------------------------------------------------

class TestResultsFormat:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), \
            "Solver must produce /app/results.json"

    def test_all_cases_present(self, results):
        for name in ALL_CASES:
            assert name in results, f"Missing case '{name}' in results"

    def test_has_required_fields(self, results):
        for name in ALL_CASES:
            entry = results[name]
            assert "heat_loss_per_meter" in entry, \
                f"'{name}' missing 'heat_loss_per_meter'"
            assert "flux_density_avg" in entry, \
                f"'{name}' missing 'flux_density_avg'"
            assert "psi_value" in entry, \
                f"'{name}' missing 'psi_value'"

    def test_values_are_positive(self, results):
        for name in ALL_CASES:
            assert results[name]["heat_loss_per_meter"] > 0, \
                f"heat_loss_per_meter must be positive for '{name}'"
            assert results[name]["flux_density_avg"] > 0, \
                f"flux_density_avg must be positive for '{name}'"
            assert results[name]["psi_value"] > 0, \
                f"psi_value must be positive for '{name}' (edge effects always add heat loss)"


# ---------------------------------------------------------------------------
# Accuracy tests: homogeneous cases (analytical series)
# ---------------------------------------------------------------------------

class TestHomogeneousAccuracy:
    """Verify homogeneous-soil results against Fourier cosine series within 1.5%."""

    @pytest.mark.parametrize("case_name", HOMOGENEOUS_CASES)
    def test_heat_loss(self, results, reference_values, case_name):
        computed = results[case_name]["heat_loss_per_meter"]
        expected = reference_values[case_name]["Q"]
        rel_err = abs(computed - expected) / expected
        assert rel_err < 0.015, (
            f"{case_name}: heat_loss={computed:.4f}, expected={expected:.4f}, "
            f"rel_error={rel_err*100:.2f}%"
        )

    @pytest.mark.parametrize("case_name", HOMOGENEOUS_CASES)
    def test_flux_density(self, results, reference_values, cases, case_name):
        B = cases[case_name]["slab_half_width"]
        Q_ref = reference_values[case_name]["Q"]
        expected_fd = Q_ref / (2.0 * B)
        computed = results[case_name]["flux_density_avg"]
        rel_err = abs(computed - expected_fd) / expected_fd
        assert rel_err < 0.015, (
            f"{case_name}: flux_density={computed:.4f}, expected={expected_fd:.4f}, "
            f"rel_error={rel_err*100:.2f}%"
        )

    @pytest.mark.parametrize("case_name", HOMOGENEOUS_CASES)
    def test_psi_value(self, results, reference_values, case_name):
        computed = results[case_name]["psi_value"]
        expected = reference_values[case_name]["psi"]
        rel_err = abs(computed - expected) / abs(expected)
        assert rel_err < 0.03, (
            f"{case_name}: psi={computed:.6f}, expected={expected:.6f}, "
            f"rel_error={rel_err*100:.2f}%"
        )


# ---------------------------------------------------------------------------
# Accuracy tests: layered soil (transfer-matrix series)
# ---------------------------------------------------------------------------

class TestLayeredAccuracy:
    """Verify two-layer soil results against transfer-matrix series within 2%."""

    def test_heat_loss(self, results, reference_values):
        computed = results["GC_LAYER"]["heat_loss_per_meter"]
        expected = reference_values["GC_LAYER"]["Q"]
        rel_err = abs(computed - expected) / expected
        assert rel_err < 0.02, (
            f"GC_LAYER: heat_loss={computed:.4f}, expected={expected:.4f}, "
            f"rel_error={rel_err*100:.2f}%"
        )

    def test_flux_density(self, results, reference_values, cases):
        B = cases["GC_LAYER"]["slab_half_width"]
        Q_ref = reference_values["GC_LAYER"]["Q"]
        expected_fd = Q_ref / (2.0 * B)
        computed = results["GC_LAYER"]["flux_density_avg"]
        rel_err = abs(computed - expected_fd) / expected_fd
        assert rel_err < 0.02

    def test_psi_value(self, results, reference_values):
        computed = results["GC_LAYER"]["psi_value"]
        expected = reference_values["GC_LAYER"]["psi"]
        rel_err = abs(computed - expected) / abs(expected)
        assert rel_err < 0.05, (
            f"GC_LAYER: psi={computed:.6f}, expected={expected:.6f}, "
            f"rel_error={rel_err*100:.2f}%"
        )


# ---------------------------------------------------------------------------
# Insulation physics tests (no analytical reference; physical bounds only)
# ---------------------------------------------------------------------------

class TestInsulationPhysics:
    """Verify insulation cases produce physically consistent results."""

    def test_insulation_reduces_heat_loss(self, results):
        """Vertical perimeter insulation must reduce Q compared to baseline."""
        Q_base = results["GC_BASE"]["heat_loss_per_meter"]
        Q_ins = results["GC_VINSUL"]["heat_loss_per_meter"]
        assert Q_ins < Q_base * 0.95, (
            f"Insulation should reduce Q by >5%: "
            f"Q_VINSUL={Q_ins:.2f} vs Q_BASE={Q_base:.2f}"
        )

    def test_insulation_lower_bound(self, results):
        """Perimeter insulation cannot eliminate all heat loss."""
        Q_base = results["GC_BASE"]["heat_loss_per_meter"]
        Q_ins = results["GC_VINSUL"]["heat_loss_per_meter"]
        assert Q_ins > Q_base * 0.30, (
            f"Q_VINSUL={Q_ins:.2f} is unreasonably low vs Q_BASE={Q_base:.2f}"
        )

    def test_combo_reduces_vs_layer(self, results):
        """Adding insulation to layered soil must reduce Q."""
        Q_layer = results["GC_LAYER"]["heat_loss_per_meter"]
        Q_combo = results["GC_COMBO"]["heat_loss_per_meter"]
        assert Q_combo < Q_layer, (
            f"Q_COMBO={Q_combo:.2f} should be < Q_LAYER={Q_layer:.2f}"
        )

    def test_combo_less_than_base(self, results):
        """Layered soil + insulation has less loss than homogeneous baseline."""
        Q_base = results["GC_BASE"]["heat_loss_per_meter"]
        Q_combo = results["GC_COMBO"]["heat_loss_per_meter"]
        assert Q_combo < Q_base, (
            f"Q_COMBO={Q_combo:.2f} should be < Q_BASE={Q_base:.2f}"
        )

    def test_insulation_reduces_psi(self, results):
        """Perimeter insulation reduces the thermal bridge coefficient."""
        psi_base = results["GC_BASE"]["psi_value"]
        psi_ins = results["GC_VINSUL"]["psi_value"]
        assert psi_ins < psi_base, (
            f"psi_VINSUL={psi_ins:.4f} should be < psi_BASE={psi_base:.4f}"
        )

    def test_combo_psi_less_than_layer(self, results):
        """Adding insulation also reduces psi for layered case."""
        psi_layer = results["GC_LAYER"]["psi_value"]
        psi_combo = results["GC_COMBO"]["psi_value"]
        assert psi_combo < psi_layer, (
            f"psi_COMBO={psi_combo:.4f} should be < psi_LAYER={psi_layer:.4f}"
        )


# ---------------------------------------------------------------------------
# Physical consistency tests (cross-case relationships)
# ---------------------------------------------------------------------------

class TestPhysicalConsistency:
    """Check physical relationships that must hold across test cases."""

    def test_conductivity_linearity(self, results):
        """Q scales exactly linearly with k (variable-coeff Laplace is linear)."""
        Q_base = results["GC_BASE"]["heat_loss_per_meter"]
        Q_highk = results["GC_HIGHK"]["heat_loss_per_meter"]
        ratio = Q_highk / Q_base
        assert abs(ratio - 2.0) < 0.05, (
            f"Q_HIGHK / Q_BASE = {ratio:.4f}, expected ~2.0"
        )

    def test_slab_width_monotonicity(self, results):
        """Total heat loss increases with slab width."""
        Q_narrow = results["GC_NARROW"]["heat_loss_per_meter"]
        Q_base = results["GC_BASE"]["heat_loss_per_meter"]
        Q_wide = results["GC_WIDE"]["heat_loss_per_meter"]
        assert Q_narrow < Q_base < Q_wide, (
            f"Expected Q_NARROW({Q_narrow:.2f}) < Q_BASE({Q_base:.2f}) "
            f"< Q_WIDE({Q_wide:.2f})"
        )

    def test_flux_density_perimeter_effect(self, results):
        """Narrower slabs have higher avg flux density (perimeter dominance)."""
        fd_narrow = results["GC_NARROW"]["flux_density_avg"]
        fd_base = results["GC_BASE"]["flux_density_avg"]
        fd_wide = results["GC_WIDE"]["flux_density_avg"]
        assert fd_narrow > fd_base > fd_wide, (
            f"Expected fd_NARROW({fd_narrow:.3f}) > fd_BASE({fd_base:.3f}) "
            f"> fd_WIDE({fd_wide:.3f})"
        )

    def test_shallow_depth_higher_loss(self, results):
        """Shallower ground boundary = less thermal resistance = more loss."""
        Q_base = results["GC_BASE"]["heat_loss_per_meter"]
        Q_shallow = results["GC_SHALLOW"]["heat_loss_per_meter"]
        assert Q_shallow > Q_base, (
            f"Expected Q_SHALLOW({Q_shallow:.2f}) > Q_BASE({Q_base:.2f})"
        )

    def test_layered_reduces_heat_loss(self, results):
        """Low-k deep layer increases total thermal resistance, reducing Q."""
        Q_base = results["GC_BASE"]["heat_loss_per_meter"]
        Q_layer = results["GC_LAYER"]["heat_loss_per_meter"]
        assert Q_layer < Q_base, (
            f"Expected Q_LAYER({Q_layer:.2f}) < Q_BASE({Q_base:.2f})"
        )

    def test_flux_consistency(self, results, cases):
        """flux_density_avg must equal heat_loss_per_meter / (2*B)."""
        for name in ALL_CASES:
            B = cases[name]["slab_half_width"]
            Q = results[name]["heat_loss_per_meter"]
            fd = results[name]["flux_density_avg"]
            expected_fd = Q / (2.0 * B)
            if expected_fd == 0:
                continue
            rel_err = abs(fd - expected_fd) / expected_fd
            assert rel_err < 0.001, (
                f"{name}: flux_density inconsistent: "
                f"fd={fd:.6f}, Q/(2B)={expected_fd:.6f}, err={rel_err:.6f}"
            )

    def test_psi_internal_consistency(self, results, cases):
        """psi_value must equal Q/dT - U_1d * 2B (self-consistency check)."""
        for name in ALL_CASES:
            cfg = cases[name]
            Q = results[name]["heat_loss_per_meter"]
            dT = cfg["T_indoor"] - cfg["T_outdoor"]
            B = cfg["slab_half_width"]
            U_1d = compute_U_1d(cfg["soil_layers"], cfg["domain_depth"])
            expected_psi = Q / dT - U_1d * 2.0 * B
            computed_psi = results[name]["psi_value"]
            if abs(expected_psi) < 1e-10:
                continue
            rel_err = abs(computed_psi - expected_psi) / abs(expected_psi)
            assert rel_err < 0.001, (
                f"{name}: psi inconsistent: "
                f"psi={computed_psi:.6f}, Q/dT-U*2B={expected_psi:.6f}"
            )

    def test_all_psi_positive(self, results):
        """Edge effects always increase heat loss beyond 1D prediction."""
        for name in ALL_CASES:
            assert results[name]["psi_value"] > 0, (
                f"{name}: psi_value={results[name]['psi_value']:.6f} should be positive"
            )
