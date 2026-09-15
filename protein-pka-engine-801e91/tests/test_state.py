
import json
import math
import subprocess
import sys
import pytest

sys.path.insert(0, "/app")


# ============================================================
# Unit tests for individual energy/calculation functions
# ============================================================

class TestHydrogenBondEnergy:
    """Test the hydrogen_bond_energy function."""

    def test_mid_range(self):
        from pka_engine import hydrogen_bond_energy
        result = hydrogen_bond_energy(2.5, 0.85, [2.0, 3.0], 1.0)
        assert result == pytest.approx(0.425, abs=1e-6)

    def test_below_min_cutoff(self):
        from pka_engine import hydrogen_bond_energy
        result = hydrogen_bond_energy(1.5, 0.85, [2.0, 3.0], 0.8)
        assert result == pytest.approx(0.68, abs=1e-6)

    def test_above_max_cutoff(self):
        from pka_engine import hydrogen_bond_energy
        result = hydrogen_bond_energy(3.5, 0.85, [2.0, 3.0], 1.0)
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_at_min_cutoff(self):
        from pka_engine import hydrogen_bond_energy
        result = hydrogen_bond_energy(2.0, 0.85, [2.0, 3.0], 1.0)
        assert result == pytest.approx(0.85, abs=1e-6)

    def test_at_max_cutoff(self):
        from pka_engine import hydrogen_bond_energy
        result = hydrogen_bond_energy(3.0, 0.85, [2.0, 3.0], 1.0)
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_negative_dpka_max_returns_absolute(self):
        from pka_engine import hydrogen_bond_energy
        result = hydrogen_bond_energy(2.0, -0.85, [2.0, 3.0], 1.0)
        assert result == pytest.approx(0.85, abs=1e-6)

    def test_angle_scaling(self):
        from pka_engine import hydrogen_bond_energy
        result = hydrogen_bond_energy(2.5, 0.85, [2.0, 3.0], 0.5)
        assert result == pytest.approx(0.2125, abs=1e-6)

    def test_wider_cutoff_range(self):
        from pka_engine import hydrogen_bond_energy
        result = hydrogen_bond_energy(2.35, 0.85, [1.85, 2.85], 1.0)
        assert result == pytest.approx(0.425, abs=1e-6)


class TestCoulombEnergy:
    """Test the coulomb_energy function."""

    def test_mid_range_half_buried(self):
        from pka_engine import coulomb_energy
        result = coulomb_energy(6.0, 0.5, 4.0, 10.0)
        expected = 244.12 / (95.0 * 6.0) * (4.0 / 6.0)
        assert result == pytest.approx(expected, abs=1e-4)

    def test_fully_buried_at_min_dist(self):
        from pka_engine import coulomb_energy
        result = coulomb_energy(3.0, 1.0, 4.0, 10.0)
        expected = 244.12 / (30.0 * 4.0)
        assert result == pytest.approx(expected, abs=1e-4)

    def test_beyond_cutoff2(self):
        from pka_engine import coulomb_energy
        result = coulomb_energy(11.0, 0.5, 4.0, 10.0)
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_at_cutoff2(self):
        from pka_engine import coulomb_energy
        result = coulomb_energy(10.0, 0.5, 4.0, 10.0)
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_fully_exposed(self):
        from pka_engine import coulomb_energy
        result = coulomb_energy(5.0, 0.0, 4.0, 10.0)
        expected = 244.12 / (160.0 * 5.0) * (5.0 / 6.0)
        assert result == pytest.approx(expected, abs=1e-4)


class TestBurialWeight:
    """Test the calculate_burial_weight function."""

    def test_mid_range(self):
        from pka_engine import calculate_burial_weight
        result = calculate_burial_weight(400, 280, 560)
        assert result == pytest.approx(120.0 / 280.0, abs=1e-6)

    def test_below_nmin(self):
        from pka_engine import calculate_burial_weight
        result = calculate_burial_weight(200, 280, 560)
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_above_nmax(self):
        from pka_engine import calculate_burial_weight
        result = calculate_burial_weight(600, 280, 560)
        assert result == pytest.approx(1.0, abs=1e-6)

    def test_at_nmin(self):
        from pka_engine import calculate_burial_weight
        result = calculate_burial_weight(280, 280, 560)
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_at_nmax(self):
        from pka_engine import calculate_burial_weight
        result = calculate_burial_weight(560, 280, 560)
        assert result == pytest.approx(1.0, abs=1e-6)


class TestScaleFactor:
    """Test the calculate_scale_factor function."""

    def test_half_weight(self):
        from pka_engine import calculate_scale_factor
        result = calculate_scale_factor(0.5, 0.25)
        assert result == pytest.approx(0.625, abs=1e-6)

    def test_zero_weight(self):
        from pka_engine import calculate_scale_factor
        result = calculate_scale_factor(0.0, 0.25)
        assert result == pytest.approx(0.25, abs=1e-6)

    def test_full_weight(self):
        from pka_engine import calculate_scale_factor
        result = calculate_scale_factor(1.0, 0.25)
        assert result == pytest.approx(1.0, abs=1e-6)


class TestResidueCharge:
    """Test the calculate_residue_charge function."""

    def test_acid_high_ph(self):
        from pka_engine import calculate_residue_charge
        result = calculate_residue_charge(3.8, 7.0, -1)
        expected = -1.0 * (10**3.2 / (1.0 + 10**3.2))
        assert result == pytest.approx(expected, abs=1e-6)

    def test_base_low_ph(self):
        from pka_engine import calculate_residue_charge
        result = calculate_residue_charge(6.5, 4.0, 1)
        expected = 1.0 * (10**2.5 / (1.0 + 10**2.5))
        assert result == pytest.approx(expected, abs=1e-6)

    def test_at_pka(self):
        from pka_engine import calculate_residue_charge
        result = calculate_residue_charge(6.5, 6.5, 1)
        assert result == pytest.approx(0.5, abs=1e-6)

    def test_acid_at_pka(self):
        from pka_engine import calculate_residue_charge
        result = calculate_residue_charge(4.0, 4.0, -1)
        assert result == pytest.approx(-0.5, abs=1e-6)

    def test_base_high_ph(self):
        from pka_engine import calculate_residue_charge
        result = calculate_residue_charge(10.5, 14.0, 1)
        expected = 1.0 * (10**(-3.5) / (1.0 + 10**(-3.5)))
        assert result == pytest.approx(expected, abs=1e-6)


class TestIsoelectricPoint:
    """Test the find_isoelectric_point function."""

    def test_simple_acid_base_pair(self):
        from pka_engine import find_isoelectric_point
        pairs = [(4.0, -1), (10.0, 1)]
        result = find_isoelectric_point(pairs, 0.0, 14.0, 1e-4)
        assert result == pytest.approx(7.0, abs=0.01)

    def test_two_acids_one_base(self):
        from pka_engine import find_isoelectric_point
        pairs = [(3.0, -1), (4.0, -1), (10.0, 1)]
        result = find_isoelectric_point(pairs, 0.0, 14.0, 1e-4)
        assert result == pytest.approx(3.5, abs=0.1)

    def test_single_group(self):
        from pka_engine import find_isoelectric_point
        pairs = [(7.0, -1), (7.0, 1)]
        result = find_isoelectric_point(pairs, 0.0, 14.0, 1e-4)
        assert result == pytest.approx(7.0, abs=0.01)


class TestComputeNetCharge:
    """Test the compute_net_charge function."""

    def test_symmetric_pair_at_midpoint(self):
        from pka_engine import compute_net_charge
        pairs = [(4.0, -1), (10.0, 1)]
        result = compute_net_charge(pairs, 7.0)
        assert result == pytest.approx(0.0, abs=0.001)

    def test_positive_at_low_ph(self):
        from pka_engine import compute_net_charge
        pairs = [(4.0, -1), (10.0, 1)]
        result = compute_net_charge(pairs, 2.0)
        assert result > 0.9

    def test_negative_at_high_ph(self):
        from pka_engine import compute_net_charge
        pairs = [(4.0, -1), (10.0, 1)]
        result = compute_net_charge(pairs, 12.0)
        assert result < -0.9


# ============================================================
# Integration tests: full pipeline on PDB structures
# ============================================================

# Reference pKa values from PROPKA 3.5 regression tests
# Order follows write_out_order: ASP, GLU, C-, HIS, CYS, TYR, LYS, ARG, N+

# sample-issue-140.pdb: 4 titratable groups (C-, CYS, ARG, N+)
REFERENCE_PKA_SAMPLE = [3.61, 9.16, 12.19, 7.83]

# 3SGB.pdb: 57 titratable groups
# 8 ASP + 5 GLU + 2 C- + 3 HIS + 10 CYS + 13 TYR + 5 LYS + 9 ARG + 2 N+
REFERENCE_PKA_3SGB = [
    3.21, 4.29, 3.47, 3.85, 4.22, 4.59, 3.55, 2.61,
    4.48, 5.27, 4.26, 5.11, 4.60, 3.63, 3.24,
    8.04, 6.15, 7.14,
    99.99, 99.99, 99.99, 99.99, 99.99, 99.99, 99.99, 99.99, 99.99, 99.99,
    10.27, 10.00, 10.33,
    10.82, 13.96, 13.90, 10.28, 10.96, 12.23, 12.62, 10.25, 10.52, 12.31,
    9.50, 10.92, 10.35, 10.44, 10.67, 11.74, 12.84, 11.95, 12.36, 11.05,
    12.89, 12.19, 12.17, 12.16,
    7.38, 7.56,
]

# 1HPX.pdb: 49 titratable groups (multi-chain homodimer with ligand)
# 8 ASP + 8 GLU + 2 C- + 2 HIS + 4 CYS + 2 TYR + 12 LYS + 8 ARG + 2 N+ + 1 ligand
REFERENCE_PKA_1HPX = [
    5.07, 3.11, 4.62, 2.55, 9.28, 1.78, 4.91, 2.13,
    4.78, 3.93, 3.65, 3.89, 4.73, 3.36, 4.07, 3.70,
    2.08, 2.11,
    6.98, 7.11,
    9.41, 11.68, 9.82, 11.61,
    9.67, 9.54,
    10.43, 10.32, 11.41, 10.54, 10.42, 10.92, 10.55, 11.01,
    11.43, 10.47, 10.41, 11.07,
    13.96, 12.41, 14.39, 12.35, 12.76, 12.42, 13.73, 12.28,
    8.96, 8.96,
    4.60,
]
REFERENCE_PI_1HPX_FOLDED = 9.54
REFERENCE_PI_1HPX_UNFOLDED = 8.90

PKA_TOLERANCE = 0.02
PI_TOLERANCE = 0.10


def _run_engine(pdb_file, timeout=180):
    """Helper: run pka_engine.py and return parsed JSON."""
    result = subprocess.run(
        [sys.executable, "/app/pka_engine.py", pdb_file],
        capture_output=True, text=True, timeout=timeout
    )
    assert result.returncode == 0, (
        "pka_engine.py failed with exit code {0:d}.\n"
        "stdout: {1:s}\nstderr: {2:s}".format(
            result.returncode, result.stdout[:500], result.stderr[:500]))
    data = json.loads(result.stdout)
    return data


class TestPipelineSampleIssue140:
    """Integration test on sample-issue-140.pdb (small: 4 titratable groups)."""

    def test_pka_values(self):
        data = _run_engine("/app/data/sample-issue-140.pdb")
        assert "pka_values" in data, "Missing 'pka_values' in output"
        pka_values = data["pka_values"]
        assert len(pka_values) == len(REFERENCE_PKA_SAMPLE), (
            "Expected {0:d} pKa values, got {1:d}: {2!r}".format(
                len(REFERENCE_PKA_SAMPLE), len(pka_values), pka_values))
        for i, (pred, ref) in enumerate(zip(pka_values, REFERENCE_PKA_SAMPLE)):
            assert pred == pytest.approx(ref, abs=PKA_TOLERANCE), (
                "pKa[{0:d}]: predicted {1:.2f}, reference {2:.2f}".format(
                    i, pred, ref))

    def test_pi_values(self):
        data = _run_engine("/app/data/sample-issue-140.pdb")
        assert "pi_folded" in data, "Missing 'pi_folded' in output"
        assert "pi_unfolded" in data, "Missing 'pi_unfolded' in output"
        assert 0 < data["pi_folded"] < 14
        assert 0 < data["pi_unfolded"] < 14


class TestPipeline3SGB:
    """Integration test on 3SGB.pdb (57 titratable groups)."""

    def test_pka_values(self):
        data = _run_engine("/app/data/3SGB.pdb")
        assert "pka_values" in data, "Missing 'pka_values' in output"
        pka_values = data["pka_values"]
        assert len(pka_values) == len(REFERENCE_PKA_3SGB), (
            "Expected {0:d} pKa values, got {1:d}".format(
                len(REFERENCE_PKA_3SGB), len(pka_values)))
        for i, (pred, ref) in enumerate(zip(pka_values, REFERENCE_PKA_3SGB)):
            assert pred == pytest.approx(ref, abs=PKA_TOLERANCE), (
                "pKa[{0:d}]: predicted {1:.2f}, reference {2:.2f}".format(
                    i, pred, ref))

    def test_pi_values(self):
        data = _run_engine("/app/data/3SGB.pdb")
        assert "pi_folded" in data
        assert "pi_unfolded" in data
        assert 4.0 < data["pi_folded"] < 13.0, (
            "pi_folded={0:.2f} seems unreasonable".format(data["pi_folded"]))
        assert 4.0 < data["pi_unfolded"] < 13.0, (
            "pi_unfolded={0:.2f} seems unreasonable".format(
                data["pi_unfolded"]))

    def test_num_disulfide_bridges(self):
        """All 10 CYS in 3SGB should be disulfide-bonded (pKa=99.99)."""
        data = _run_engine("/app/data/3SGB.pdb")
        pka_values = data["pka_values"]
        # CYS values are at indices 18-27
        # (after 8 ASP + 5 GLU + 2 C- + 3 HIS = 18)
        cys_pkas = pka_values[18:28]
        assert len(cys_pkas) == 10, (
            "Expected 10 CYS values, got {0:d}".format(len(cys_pkas)))
        for i, pka in enumerate(cys_pkas):
            assert pka == pytest.approx(99.99, abs=0.01), (
                "CYS[{0:d}] should be 99.99 (disulfide), got {1:.2f}".format(
                    i, pka))


class TestPipeline1HPX:
    """Integration test on 1HPX.pdb (49 titratable groups, multi-chain homodimer)."""

    def test_pka_values(self):
        data = _run_engine("/app/data/1HPX.pdb")
        assert "pka_values" in data, "Missing 'pka_values' in output"
        pka_values = data["pka_values"]
        assert len(pka_values) == len(REFERENCE_PKA_1HPX), (
            "Expected {0:d} pKa values, got {1:d}".format(
                len(REFERENCE_PKA_1HPX), len(pka_values)))
        for i, (pred, ref) in enumerate(zip(pka_values, REFERENCE_PKA_1HPX)):
            assert pred == pytest.approx(ref, abs=PKA_TOLERANCE), (
                "pKa[{0:d}]: predicted {1:.2f}, reference {2:.2f}".format(
                    i, pred, ref))

    def test_pi_folded(self):
        data = _run_engine("/app/data/1HPX.pdb")
        assert "pi_folded" in data, "Missing 'pi_folded' in output"
        assert data["pi_folded"] == pytest.approx(
            REFERENCE_PI_1HPX_FOLDED, abs=PI_TOLERANCE), (
            "pi_folded={0:.2f}, expected {1:.2f}".format(
                data["pi_folded"], REFERENCE_PI_1HPX_FOLDED))

    def test_pi_unfolded(self):
        data = _run_engine("/app/data/1HPX.pdb")
        assert "pi_unfolded" in data, "Missing 'pi_unfolded' in output"
        assert data["pi_unfolded"] == pytest.approx(
            REFERENCE_PI_1HPX_UNFOLDED, abs=PI_TOLERANCE), (
            "pi_unfolded={0:.2f}, expected {1:.2f}".format(
                data["pi_unfolded"], REFERENCE_PI_1HPX_UNFOLDED))


class TestPIConsistency:
    """Verify that pi_folded is consistent with pKa values and charge model."""

    def test_sample_issue_140_pi_consistency(self):
        """pi_folded must equal pH of zero net charge from folded pKa values."""
        data = _run_engine("/app/data/sample-issue-140.pdb")
        pka_values = data["pka_values"]
        pi_folded = data["pi_folded"]

        # sample-issue-140 groups in write_out_order: C-(-1), CYS(-1), ARG(+1), N+(+1)
        charge_signs = [-1, -1, 1, 1]
        pairs = list(zip(pka_values, charge_signs))

        from pka_engine import compute_net_charge, find_isoelectric_point

        # Net charge at reported pI should be near zero
        net_charge_at_pi = compute_net_charge(pairs, pi_folded)
        assert abs(net_charge_at_pi) < 0.10, (
            "Net charge at pi_folded={0:.2f} should be near zero, got {1:.4f}".format(
                pi_folded, net_charge_at_pi))

        # find_isoelectric_point should agree with reported pi_folded
        pi_calc = find_isoelectric_point(pairs, 0.0, 14.0, 1e-4)
        assert pi_calc == pytest.approx(pi_folded, abs=PI_TOLERANCE), (
            "find_isoelectric_point={0:.4f}, pi_folded={1:.2f}".format(
                pi_calc, pi_folded))

    def test_1hpx_pi_net_charge_near_zero(self):
        """At the reported pi_folded, net charge from pKa values should be near zero.
        1HPX ligand is a NAR-type group (charge +1)."""
        data = _run_engine("/app/data/1HPX.pdb")
        pka_values = data["pka_values"]
        pi_folded = data["pi_folded"]

        # 1HPX: 8 ASP(-1) + 8 GLU(-1) + 2 C-(-1) + 2 HIS(+1) + 4 CYS(-1)
        #      + 2 TYR(-1) + 12 LYS(+1) + 8 ARG(+1) + 2 N+(+1) + 1 ligand(+1)
        charge_signs = (
            [-1]*8 + [-1]*8 + [-1]*2 + [1]*2 + [-1]*4
            + [-1]*2 + [1]*12 + [1]*8 + [1]*2 + [1]*1
        )
        assert len(charge_signs) == len(pka_values), (
            "Expected {0:d} charge signs, got {1:d}".format(
                len(pka_values), len(charge_signs)))
        pairs = list(zip(pka_values, charge_signs))

        from pka_engine import compute_net_charge, find_isoelectric_point

        net_charge_at_pi = compute_net_charge(pairs, pi_folded)
        assert abs(net_charge_at_pi) < 0.10, (
            "Net charge at pi_folded={0:.2f} should be near zero, got {1:.4f}".format(
                pi_folded, net_charge_at_pi))

        pi_calc = find_isoelectric_point(pairs, 0.0, 14.0, 1e-4)
        assert pi_calc == pytest.approx(pi_folded, abs=PI_TOLERANCE), (
            "find_isoelectric_point={0:.4f}, pi_folded={1:.2f}".format(
                pi_calc, pi_folded))
