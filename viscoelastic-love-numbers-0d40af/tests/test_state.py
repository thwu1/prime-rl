
"""
Tests for viscoelastic Love number computation.

Reference data from TABOO (Spada, 2003) output for the Yuen-Sabadini-Boschi
(1982) 2-layer Earth model: NV=2, CODE=2, vis=[2.0, 1.0] x 10^21 Pa.s.
"""

import json
import os
import subprocess
import pytest

# Reference spectrum (8 physical modes per degree, all real and negative)
REF_SPECTRUM = {
    2:  [-0.0006257818, -0.03546595, -0.2401649, -1.339931,
         -2.641371, -2.683034, -2.78459, -3.424],
    5:  [-0.002463284, -0.1170848, -0.2462677, -0.4376829,
         -2.641371, -2.656708, -2.839813, -3.424],
    10: [-0.005044046, -0.1473355, -0.1992719, -0.2860033,
         -2.641371, -2.678677, -2.851524, -3.424],
}

REF_H_ELASTIC = {
    2:  -4.9145017315e-01,
    5:  -5.1454286258e-01,
    10: -7.5370088631e-01,
    15: -9.9949289687e-01,
    20: -1.1972950349e+00,
}

REF_L_ELASTIC = {
    2:  -1.3610668695e-01,
    5:  -5.6648655596e-02,
    10: -4.2598491046e-02,
    15: -3.1061188719e-02,
    20: -2.4147819107e-02,
}

REF_H_FLUID = {
    2:  -2.1351907473e+00,
    5:  -4.7027796828e+00,
    10: -8.9717201460e+00,
    15: -1.3168892381e+01,
    20: -1.7157339163e+01,
}

REF_L_FLUID = {
    2:  -9.4876528230e-01,
    5:  -3.6010806621e-01,
    10: -1.3411435966e-01,
    15: -3.5378762027e-02,
    20:  2.8488572184e-02,
}

ELASTIC_RTOL = 5e-4
FLUID_RTOL = 5e-3
SPECTRUM_RTOL = 5e-3


def rel_err(computed, reference):
    if abs(reference) < 1e-15:
        return abs(computed)
    return abs(computed - reference) / abs(reference)


@pytest.fixture(scope="session")
def results():
    script = "/app/love_numbers.py"
    assert os.path.isfile(script), f"Implementation file {script} not found"

    result = subprocess.run(
        ["python3", script],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"love_numbers.py failed with exit code {result.returncode}\n"
        f"STDOUT: {result.stdout[-2000:]}\n"
        f"STDERR: {result.stderr[-2000:]}"
    )

    output_path = "/app/output/results.json"
    assert os.path.isfile(output_path), f"Output file {output_path} not found"

    with open(output_path) as f:
        data = json.load(f)
    return data


def _get_value(results, section, component, degree):
    degrees = results["degrees"]
    idx = degrees.index(degree)
    return results[section][component][idx]


class TestResultsStructure:
    def test_has_degrees(self, results):
        assert "degrees" in results
        assert 2 in results["degrees"]
        assert 30 in results["degrees"]

    def test_has_elastic(self, results):
        for comp in ["h", "l", "k"]:
            assert comp in results["elastic"]
            assert len(results["elastic"][comp]) == len(results["degrees"])

    def test_has_fluid(self, results):
        for comp in ["h", "l", "k"]:
            assert comp in results["fluid"]
            assert len(results["fluid"][comp]) == len(results["degrees"])

    def test_has_spectrum(self, results):
        assert "spectrum" in results
        assert "2" in results["spectrum"]

    def test_has_residues(self, results):
        for comp in ["h", "l", "k"]:
            assert comp in results["residues"]


class TestElasticLoveNumbers:
    @pytest.mark.parametrize("degree", [2, 5, 10, 15, 20])
    def test_h_elastic(self, results, degree):
        computed = _get_value(results, "elastic", "h", degree)
        reference = REF_H_ELASTIC[degree]
        err = rel_err(computed, reference)
        assert err < ELASTIC_RTOL, (
            f"h_e(l={degree}): computed={computed:.8e}, "
            f"reference={reference:.8e}, rel_err={err:.2e}"
        )

    @pytest.mark.parametrize("degree", [2, 5, 10, 15, 20])
    def test_l_elastic(self, results, degree):
        computed = _get_value(results, "elastic", "l", degree)
        reference = REF_L_ELASTIC[degree]
        err = rel_err(computed, reference)
        assert err < ELASTIC_RTOL, (
            f"l_e(l={degree}): computed={computed:.8e}, "
            f"reference={reference:.8e}, rel_err={err:.2e}"
        )


class TestFluidLoveNumbers:
    @pytest.mark.parametrize("degree", [2, 5, 10, 15, 20])
    def test_h_fluid(self, results, degree):
        computed = _get_value(results, "fluid", "h", degree)
        reference = REF_H_FLUID[degree]
        err = rel_err(computed, reference)
        assert err < FLUID_RTOL, (
            f"h_f(l={degree}): computed={computed:.8e}, "
            f"reference={reference:.8e}, rel_err={err:.2e}"
        )

    @pytest.mark.parametrize("degree", [2, 5, 10, 15, 20])
    def test_l_fluid(self, results, degree):
        computed = _get_value(results, "fluid", "l", degree)
        reference = REF_L_FLUID[degree]
        err = rel_err(computed, reference)
        assert err < FLUID_RTOL, (
            f"l_f(l={degree}): computed={computed:.8e}, "
            f"reference={reference:.8e}, rel_err={err:.2e}"
        )


class TestRelaxationSpectrum:
    @pytest.mark.parametrize("degree", [2, 5, 10])
    def test_number_of_modes(self, results, degree):
        modes = results["spectrum"][str(degree)]
        ref_modes = REF_SPECTRUM[degree]
        assert len(modes) == len(ref_modes), (
            f"Degree {degree}: expected {len(ref_modes)} physical modes, "
            f"got {len(modes)}"
        )

    @pytest.mark.parametrize("degree", [2, 5, 10])
    def test_mode_values(self, results, degree):
        modes = sorted(results["spectrum"][str(degree)], key=lambda x: abs(x))
        ref_modes = sorted(REF_SPECTRUM[degree], key=lambda x: abs(x))
        for i, (comp, ref) in enumerate(zip(modes, ref_modes)):
            err = rel_err(comp, ref)
            assert err < SPECTRUM_RTOL, (
                f"Degree {degree}, mode {i}: computed s={comp:.6e}, "
                f"reference s={ref:.6e}, rel_err={err:.2e}"
            )

    def test_all_modes_negative(self, results):
        for deg_str, modes in results["spectrum"].items():
            for s in modes:
                assert s < 0, f"Degree {deg_str}: non-negative mode s={s}"


class TestConsistency:
    @pytest.mark.parametrize("degree", [2, 5, 10, 15, 20])
    def test_h_fluid_consistency(self, results, degree):
        """Verify h_f = h_e - sum(h_v_k / s_k)."""
        h_e = _get_value(results, "elastic", "h", degree)
        h_f = _get_value(results, "fluid", "h", degree)
        modes = results["spectrum"][str(degree)]
        residues = results["residues"]["h"][str(degree)]

        h_f_check = h_e
        for s_k, h_v_k in zip(modes, residues):
            h_f_check -= h_v_k / s_k

        err = rel_err(h_f_check, h_f)
        assert err < 1e-8, (
            f"h_f consistency (degree {degree}): "
            f"h_f={h_f:.8e}, h_e - sum(h_v/s)={h_f_check:.8e}, err={err:.2e}"
        )

    @pytest.mark.parametrize("degree", [2, 5, 10, 15, 20])
    def test_l_fluid_consistency(self, results, degree):
        """Verify l_f = l_e - sum(l_v_k / s_k)."""
        l_e = _get_value(results, "elastic", "l", degree)
        l_f = _get_value(results, "fluid", "l", degree)
        modes = results["spectrum"][str(degree)]
        residues = results["residues"]["l"][str(degree)]

        l_f_check = l_e
        for s_k, l_v_k in zip(modes, residues):
            l_f_check -= l_v_k / s_k

        err = rel_err(l_f_check, l_f)
        assert err < 1e-8, (
            f"l_f consistency (degree {degree}): "
            f"l_f={l_f:.8e}, l_e - sum(l_v/s)={l_f_check:.8e}, err={err:.2e}"
        )

    @pytest.mark.parametrize("degree", [2, 5, 10, 15, 20])
    def test_k_fluid_consistency(self, results, degree):
        """Verify k_f = k_e - sum(k_v_k / s_k)."""
        k_e = _get_value(results, "elastic", "k", degree)
        k_f = _get_value(results, "fluid", "k", degree)
        modes = results["spectrum"][str(degree)]
        residues = results["residues"]["k"][str(degree)]

        k_f_check = k_e
        for s_k, k_v_k in zip(modes, residues):
            k_f_check -= k_v_k / s_k

        err = rel_err(k_f_check, k_f)
        assert err < 1e-8, (
            f"k_f consistency (degree {degree}): "
            f"k_f={k_f:.8e}, k_e - sum(k_v/s)={k_f_check:.8e}, err={err:.2e}"
        )

    def test_elastic_h_negative(self, results):
        for val in results["elastic"]["h"]:
            assert val < 0, f"h_e should be negative, got {val}"

    def test_elastic_k_negative(self, results):
        for val in results["elastic"]["k"]:
            assert val < 0, f"k_e should be negative, got {val}"

    def test_fluid_h_more_negative_than_elastic(self, results):
        for h_e, h_f in zip(results["elastic"]["h"], results["fluid"]["h"]):
            assert h_f < h_e, (
                f"h_f={h_f:.6e} should be more negative than h_e={h_e:.6e}"
            )
