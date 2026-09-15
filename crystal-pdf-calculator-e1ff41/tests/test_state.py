"""Tests for the pair distribution function calculator.

"""

import os
import subprocess
import numpy as np
import pytest


REF_FGR = "/tests/Ni-fit.fgr"
NI_STRU = "/app/data/Ni.stru"
NI_PRIM_STRU = "/app/data/Ni_primitive.stru"
NI_CIF = "/app/data/Ni.cif"
CALC_SCRIPT = "/app/pdf_calc.py"
OUTPUT_CONV = "/app/output/Ni_conv.dat"
OUTPUT_PRIM = "/app/output/Ni_prim.dat"
OUTPUT_CIF = "/app/output/Ni_cif.dat"
OUTPUT_DAMP = "/app/output/Ni_damp.dat"

RMAX = 10.0
RSTEP = 0.01
EXPECTED_NPTS = 1001  # 0, 0.01, ..., 10.00


def _max_norm_diff(yobs, ycalc):
    """Maximum difference normalized by the max absolute value of yobs."""
    yobs = np.asarray(yobs, dtype=float)
    ycalc = np.asarray(ycalc, dtype=float)
    obsmax = np.max(np.fabs(yobs))
    if obsmax == 0:
        obsmax = 1.0
    return np.max(np.fabs((yobs - ycalc) / obsmax))


def _load_two_column(path):
    """Load a two-column whitespace-separated file, skipping comment lines."""
    r_vals = []
    g_vals = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                r_vals.append(float(parts[0]))
                g_vals.append(float(parts[1]))
    return np.array(r_vals), np.array(g_vals)


def _run_calc(stru_path, output_path, qdamp=0.0):
    """Run the PDF calculator and return (r, G) arrays."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cmd = [
        "python3", CALC_SCRIPT,
        stru_path,
        "--rmax", str(RMAX),
        "--rstep", str(RSTEP),
        "--qdamp", str(qdamp),
        "--output", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, (
        f"pdf_calc.py failed with exit code {result.returncode}.\n"
        f"stdout: {result.stdout[:500]}\n"
        f"stderr: {result.stderr[:500]}"
    )
    assert os.path.isfile(output_path), f"Output file {output_path} not created"
    return _load_two_column(output_path)


@pytest.fixture(scope="module")
def reference_data():
    """Load reference G(r) data."""
    r_ref, g_ref = _load_two_column(REF_FGR)
    return r_ref, g_ref


@pytest.fixture(scope="module")
def conv_result():
    """Run PDF calculator on conventional Ni cell, qdamp=0."""
    return _run_calc(NI_STRU, OUTPUT_CONV, qdamp=0.0)


@pytest.fixture(scope="module")
def prim_result():
    """Run PDF calculator on primitive Ni cell, qdamp=0."""
    return _run_calc(NI_PRIM_STRU, OUTPUT_PRIM, qdamp=0.0)


@pytest.fixture(scope="module")
def cif_result():
    """Run PDF calculator on CIF Ni structure, qdamp=0."""
    return _run_calc(NI_CIF, OUTPUT_CIF, qdamp=0.0)


@pytest.fixture(scope="module")
def conv_result_damped():
    """Run PDF calculator on conventional Ni cell, qdamp=0.1."""
    return _run_calc(NI_STRU, OUTPUT_DAMP, qdamp=0.1)


class TestScriptExists:
    def test_script_exists(self):
        assert os.path.isfile(CALC_SCRIPT), (
            f"{CALC_SCRIPT} does not exist"
        )


class TestNoPrebuiltPDF:
    """Verify the solver implemented PDF computation from scratch."""

    def test_no_forbidden_imports(self):
        with open(CALC_SCRIPT) as f:
            content = f.read()
        forbidden = ["diffpy.srreal", "PDFCalculator", "DebyePDFCalculator"]
        for token in forbidden:
            assert token not in content, (
                f"Found '{token}' in pdf_calc.py — implement PDF computation "
                f"from scratch without pre-built PDF calculators"
            )


class TestConventionalCell:
    """Tests using the 4-atom conventional FCC cell."""

    def test_output_length(self, conv_result):
        r_calc, g_calc = conv_result
        assert len(g_calc) == EXPECTED_NPTS, (
            f"Expected {EXPECTED_NPTS} grid points, got {len(g_calc)}"
        )

    def test_r_grid(self, conv_result):
        r_calc, g_calc = conv_result
        r_expected = np.arange(EXPECTED_NPTS) * RSTEP
        assert np.allclose(r_calc, r_expected, atol=1e-6), (
            "r-grid values do not match expected spacing"
        )

    def test_g_at_zero(self, conv_result):
        r_calc, g_calc = conv_result
        assert abs(g_calc[0]) < 1e-6, (
            f"G(r=0) should be 0, got {g_calc[0]}"
        )

    def test_match_reference(self, conv_result, reference_data):
        r_calc, g_calc = conv_result
        r_ref, g_ref = reference_data
        n = min(len(g_ref), len(g_calc))
        mnd = _max_norm_diff(g_ref[:n], g_calc[:n])
        assert mnd < 0.012, (
            f"maxNormDiff between conventional cell G(r) and reference "
            f"is {mnd:.6f}, must be < 0.012"
        )

    def test_baseline_slope(self, conv_result):
        """At small r (before first peak), G(r) should follow -4*pi*r*rho0."""
        r_calc, g_calc = conv_result
        idx = 50  # r = 0.50
        r_val = r_calc[idx]
        g_val = g_calc[idx]
        rho0 = 4.0 / (3.52 ** 3)
        expected_baseline = -4.0 * np.pi * r_val * rho0
        rel_err = abs(g_val - expected_baseline) / abs(expected_baseline)
        assert rel_err < 0.10, (
            f"Baseline at r={r_val:.2f}: G={g_val:.4f}, "
            f"expected ~{expected_baseline:.4f}, rel_err={rel_err:.4f}"
        )

    def test_first_peak_position(self, conv_result):
        """First peak should be near the FCC nearest-neighbor distance."""
        r_calc, g_calc = conv_result
        mask = (r_calc >= 2.0) & (r_calc <= 3.0)
        r_sub = r_calc[mask]
        g_sub = g_calc[mask]
        peak_idx = np.argmax(g_sub)
        peak_r = r_sub[peak_idx]
        assert abs(peak_r - 2.489) < 0.03, (
            f"First peak at r={peak_r:.3f}, expected near 2.489 A"
        )

    def test_first_peak_height(self, conv_result):
        """First peak should have significant positive amplitude."""
        r_calc, g_calc = conv_result
        mask = (r_calc >= 2.0) & (r_calc <= 3.0)
        peak_height = np.max(g_calc[mask])
        assert peak_height > 20.0, (
            f"First peak height {peak_height:.2f} is too low (expected >20)"
        )


class TestPrimitiveCell:
    """Tests using the 1-atom primitive rhombohedral cell."""

    def test_output_length(self, prim_result):
        r_calc, g_calc = prim_result
        assert len(g_calc) == EXPECTED_NPTS, (
            f"Expected {EXPECTED_NPTS} grid points, got {len(g_calc)}"
        )

    def test_g_at_zero(self, prim_result):
        r_calc, g_calc = prim_result
        assert abs(g_calc[0]) < 1e-6, (
            f"G(r=0) should be 0, got {g_calc[0]}"
        )

    def test_match_reference(self, prim_result, reference_data):
        r_calc, g_calc = prim_result
        r_ref, g_ref = reference_data
        n = min(len(g_ref), len(g_calc))
        mnd = _max_norm_diff(g_ref[:n], g_calc[:n])
        assert mnd < 0.012, (
            f"maxNormDiff between primitive cell G(r) and reference "
            f"is {mnd:.6f}, must be < 0.012"
        )

    def test_first_peak_position(self, prim_result):
        """First peak for primitive cell should also be near 2.489 A."""
        r_calc, g_calc = prim_result
        mask = (r_calc >= 2.0) & (r_calc <= 3.0)
        r_sub = r_calc[mask]
        g_sub = g_calc[mask]
        peak_idx = np.argmax(g_sub)
        peak_r = r_sub[peak_idx]
        assert abs(peak_r - 2.489) < 0.03, (
            f"First peak at r={peak_r:.3f}, expected near 2.489 A"
        )


class TestConsistency:
    """Verify that conventional and primitive cells give the same G(r)."""

    def test_cells_agree(self, conv_result, prim_result):
        r_conv, g_conv = conv_result
        r_prim, g_prim = prim_result
        n = min(len(g_conv), len(g_prim))
        mnd = _max_norm_diff(g_conv[:n], g_prim[:n])
        assert mnd < 0.005, (
            f"maxNormDiff between conventional and primitive cell G(r) "
            f"is {mnd:.6f}, must be < 0.005"
        )


class TestCIFInput:
    """Tests using CIF-format Ni structure with symmetry expansion."""

    def test_output_length(self, cif_result):
        r_calc, g_calc = cif_result
        assert len(g_calc) == EXPECTED_NPTS, (
            f"Expected {EXPECTED_NPTS} grid points from CIF, got {len(g_calc)}"
        )

    def test_g_at_zero(self, cif_result):
        r_calc, g_calc = cif_result
        assert abs(g_calc[0]) < 1e-6, (
            f"CIF: G(r=0) should be 0, got {g_calc[0]}"
        )

    def test_baseline_slope(self, cif_result):
        """Baseline from CIF should match -4*pi*r*rho0."""
        r_calc, g_calc = cif_result
        idx = 50  # r = 0.50
        r_val = r_calc[idx]
        g_val = g_calc[idx]
        # CIF has same cell as Ni.stru: a=3.52, 4 atoms
        rho0 = 4.0 / (3.52 ** 3)
        expected_baseline = -4.0 * np.pi * r_val * rho0
        rel_err = abs(g_val - expected_baseline) / abs(expected_baseline)
        assert rel_err < 0.10, (
            f"CIF baseline at r={r_val:.2f}: G={g_val:.4f}, "
            f"expected ~{expected_baseline:.4f}, rel_err={rel_err:.4f}"
        )

    def test_first_peak_position(self, cif_result):
        """CIF first peak should be near a/sqrt(2)."""
        r_calc, g_calc = cif_result
        mask = (r_calc >= 2.0) & (r_calc <= 3.0)
        r_sub = r_calc[mask]
        g_sub = g_calc[mask]
        peak_idx = np.argmax(g_sub)
        peak_r = r_sub[peak_idx]
        # a=3.52, NN = 3.52/sqrt(2) = 2.489
        assert abs(peak_r - 2.489) < 0.05, (
            f"CIF first peak at r={peak_r:.3f}, expected near 2.489 A"
        )

    def test_first_peak_height(self, cif_result):
        """CIF first peak should have significant amplitude."""
        r_calc, g_calc = cif_result
        mask = (r_calc >= 2.0) & (r_calc <= 3.0)
        peak_height = np.max(g_calc[mask])
        assert peak_height > 15.0, (
            f"CIF first peak height {peak_height:.2f} too low (expected >15)"
        )


class TestCIFSTRUConsistency:
    """CIF and STRU with same parameters must produce equivalent G(r)."""

    def test_cif_stru_agree(self, conv_result, cif_result):
        r_conv, g_conv = conv_result
        r_cif, g_cif = cif_result
        n = min(len(g_conv), len(g_cif))
        mnd = _max_norm_diff(g_conv[:n], g_cif[:n])
        assert mnd < 0.005, (
            f"maxNormDiff between CIF and STRU outputs is {mnd:.6f}, "
            f"must be < 0.005"
        )


class TestQdamp:
    """Verify Q-resolution damping envelope attenuates peaks at large r."""

    def test_damping_attenuates_far_peaks(self, conv_result, conv_result_damped):
        """With qdamp=0.1, peaks at 7-9 A should be attenuated vs qdamp=0."""
        r0, g0 = conv_result  # qdamp=0
        rd, gd = conv_result_damped  # qdamp=0.1

        mask_far = (r0 >= 7.0) & (r0 <= 9.0)
        max_far_undamped = np.max(np.abs(g0[mask_far]))
        max_far_damped = np.max(np.abs(gd[mask_far]))

        assert max_far_damped < 0.85 * max_far_undamped, (
            f"Qdamp=0.1 not attenuating far peaks: undamped max={max_far_undamped:.3f}, "
            f"damped max={max_far_damped:.3f}, ratio={max_far_damped/max_far_undamped:.3f}"
        )

    def test_damping_preserves_near_peaks(self, conv_result, conv_result_damped):
        """Near peaks (2-3 A) should be only slightly affected by qdamp=0.1."""
        r0, g0 = conv_result
        rd, gd = conv_result_damped

        mask_near = (r0 >= 2.0) & (r0 <= 3.0)
        peak_undamped = np.max(g0[mask_near])
        peak_damped = np.max(gd[mask_near])

        # At r~2.5, envelope = exp(-0.1^2 * 2.5^2 / 2) ~ 0.969
        # So damped peak should be > 90% of undamped
        assert peak_damped > 0.90 * peak_undamped, (
            f"Qdamp=0.1 over-attenuating near peaks: undamped={peak_undamped:.2f}, "
            f"damped={peak_damped:.2f}"
        )

    def test_damped_output_length(self, conv_result_damped):
        """Damped output should have correct grid length."""
        r_calc, g_calc = conv_result_damped
        assert len(g_calc) == EXPECTED_NPTS, (
            f"Damped output expected {EXPECTED_NPTS} points, got {len(g_calc)}"
        )
