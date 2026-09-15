"""
Tests for the elastic constants calculator and force verification framework.

Verifies correctness via self-consistency checks, physical constraints,
independent cross-validation, and generality across crystal structures.
"""


import json
import os
import shutil
import subprocess

import numpy as np
import pytest
from scipy.optimize import minimize_scalar


def read_results():
    with open("/app/results.json") as f:
        return json.load(f)


def _morse_energy_indep(positions, cell, D, alpha, r0, cutoff, pbc=True):
    """Independent Morse energy implementation for cross-validation."""
    N = len(positions)
    inv_cell = np.linalg.inv(cell) if pbc else None
    energy = 0.0
    for i in range(N):
        rij = positions[i + 1 :] - positions[i]
        if pbc:
            frac = rij @ inv_cell
            frac -= np.round(frac)
            rij = frac @ cell
        r = np.linalg.norm(rij, axis=1)
        mask = (r < cutoff) & (r > 1e-12)
        r_m = r[mask]
        if len(r_m) > 0:
            exp1 = np.exp(-alpha * (r_m - r0))
            exp2 = exp1**2
            energy += np.sum(D * (exp2 - 2 * exp1))
    return energy


def _build_supercell_indep(a, structure, nx, ny, nz):
    """Independent supercell builder for cross-validation."""
    basis_map = {
        "fcc": np.array(
            [[0, 0, 0], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]], dtype=float
        ),
        "bcc": np.array([[0, 0, 0], [0.5, 0.5, 0.5]], dtype=float),
        "sc": np.array([[0, 0, 0]], dtype=float),
    }
    basis = basis_map[structure]
    positions = []
    for ix in range(nx):
        for iy in range(ny):
            for iz in range(nz):
                for b in basis:
                    positions.append((b + [ix, iy, iz]) * a)
    cell = np.diag([a * nx, a * ny, a * nz]).astype(float)
    return np.array(positions), cell


class TestFCCElasticVerifier:
    """Tests using the provided FCC configuration."""

    @pytest.fixture(autouse=True, scope="class")
    def run_verifier(self):
        """Run the elastic verifier before any tests."""
        result = subprocess.run(
            ["python3", "/app/elastic_verifier.py"],
            capture_output=True,
            text=True,
            timeout=600,
            cwd="/app",
        )
        assert result.returncode == 0, (
            f"elastic_verifier.py failed:\nSTDOUT: {result.stdout[-500:]}\n"
            f"STDERR: {result.stderr[-500:]}"
        )

    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found"

    def test_results_schema(self):
        r = read_results()
        assert "equilibrium_lattice_constant" in r
        assert isinstance(r["equilibrium_lattice_constant"], (int, float))

        ec = r["elastic_constants"]
        for key in ["C11", "C12", "C44", "bulk_modulus"]:
            assert key in ec, f"Missing elastic constant: {key}"
            assert isinstance(ec[key], (int, float)), f"{key} is not numeric"

        fv = r["force_verification"]
        for key in [
            "max_relative_error",
            "grade",
            "num_atoms_tested",
            "num_components_tested",
            "num_outliers_excluded",
        ]:
            assert key in fv, f"Missing force_verification field: {key}"

        assert fv["grade"] in ("A", "B", "C", "D", "F"), f"Invalid grade: {fv['grade']}"
        assert isinstance(fv["num_atoms_tested"], int)
        assert isinstance(fv["num_components_tested"], int)
        assert isinstance(fv["num_outliers_excluded"], int)

    def test_bulk_modulus_self_consistency(self):
        """B must equal (C11 + 2*C12) / 3."""
        r = read_results()
        ec = r["elastic_constants"]
        B_computed = (ec["C11"] + 2 * ec["C12"]) / 3.0
        rel_err = abs(ec["bulk_modulus"] - B_computed) / abs(B_computed)
        assert rel_err < 1e-6, (
            f"Bulk modulus inconsistency: reported={ec['bulk_modulus']:.8e}, "
            f"computed=(C11+2C12)/3={B_computed:.8e}, rel_err={rel_err:.2e}"
        )

    def test_cauchy_relation(self):
        """For a central-force pair potential, the Cauchy relation C12 ≈ C44
        must hold approximately. Tolerance accounts for finite-cutoff effects
        and numerical differentiation errors in the Hessian computation."""
        r = read_results()
        ec = r["elastic_constants"]
        denom = max(abs(ec["C12"]), abs(ec["C44"]), 1e-20)
        rel_diff = abs(ec["C12"] - ec["C44"]) / denom
        assert rel_diff < 0.06, (
            f"Cauchy relation violated: C12={ec['C12']:.8e}, C44={ec['C44']:.8e}, "
            f"relative difference={rel_diff:.4e}"
        )

    def test_physical_constraints(self):
        """Elastic constants must satisfy Born stability criteria for cubic crystals."""
        r = read_results()
        ec = r["elastic_constants"]
        assert ec["C11"] > 0, f"C11={ec['C11']} must be positive"
        assert ec["C44"] > 0, f"C44={ec['C44']} must be positive"
        assert ec["C11"] > abs(ec["C12"]), (
            f"C11={ec['C11']} must exceed |C12|={abs(ec['C12'])}"
        )
        assert ec["bulk_modulus"] > 0, f"B={ec['bulk_modulus']} must be positive"

    def test_force_verification_grade(self):
        """A smooth Morse potential should achieve grade A or B."""
        r = read_results()
        grade = r["force_verification"]["grade"]
        assert grade in ("A", "B"), (
            f"Expected grade A or B for Morse potential, got {grade} "
            f"(max_error={r['force_verification']['max_relative_error']:.3e})"
        )

    def test_force_verification_atom_count(self):
        """2x2x2 FCC cluster should have 32 atoms = 96 components."""
        r = read_results()
        fv = r["force_verification"]
        assert fv["num_atoms_tested"] == 32, (
            f"Expected 32 atoms in 2x2x2 FCC cluster, got {fv['num_atoms_tested']}"
        )
        expected_components = fv["num_atoms_tested"] * 3
        assert fv["num_components_tested"] == expected_components, (
            f"Expected {expected_components} components, got {fv['num_components_tested']}"
        )

    def test_lattice_constant_physically_reasonable(self):
        r = read_results()
        a = r["equilibrium_lattice_constant"]
        assert 3.0 < a < 6.0, f"Lattice constant {a} is outside reasonable range [3, 6] A"

    def test_elastic_constants_reasonable_magnitude(self):
        """Elastic constants should be in a reasonable range for a Morse potential."""
        r = read_results()
        ec = r["elastic_constants"]
        for name in ["C11", "C12", "C44", "bulk_modulus"]:
            val = ec[name]
            assert 0 < abs(val) < 50, (
                f"{name}={val} eV/A^3 outside reasonable range"
            )

    def test_independent_lattice_constant(self):
        """Cross-validate equilibrium lattice constant with independent computation."""
        with open("/app/potential_params.json") as f:
            pp = json.load(f)
        with open("/app/config.json") as f:
            cfg = json.load(f)

        D = pp["parameters"]["D"]
        alpha = pp["parameters"]["alpha"]
        r0 = pp["parameters"]["r0"]
        rc = pp["parameters"]["cutoff"]
        structure = cfg["crystal_structure"]

        def energy_per_atom(a):
            positions, cell = _build_supercell_indep(a, structure, 3, 3, 3)
            e = _morse_energy_indep(positions, cell, D, alpha, r0, rc, pbc=True)
            return e / len(positions)

        res = minimize_scalar(
            energy_per_atom, bounds=(2.5, 6.0), method="bounded",
            options={"xatol": 1e-12}
        )
        a_eq_ref = res.x

        r = read_results()
        a_eq = r["equilibrium_lattice_constant"]
        rel_err = abs(a_eq - a_eq_ref) / a_eq_ref
        assert rel_err < 1e-4, (
            f"Lattice constant mismatch: solver={a_eq:.8f}, "
            f"independent={a_eq_ref:.8f}, rel_err={rel_err:.2e}"
        )

    def test_independent_c11(self):
        """Cross-validate C11 via independent finite-difference computation."""
        with open("/app/potential_params.json") as f:
            pp = json.load(f)
        with open("/app/config.json") as f:
            cfg = json.load(f)

        D = pp["parameters"]["D"]
        alpha = pp["parameters"]["alpha"]
        r0 = pp["parameters"]["r0"]
        rc = pp["parameters"]["cutoff"]
        structure = cfg["crystal_structure"]
        sc = 3

        r = read_results()
        a_eq = r["equilibrium_lattice_constant"]

        def energy_density_uniaxial(eps_xx):
            """Energy density under uniaxial strain eps_xx."""
            positions, _ = _build_supercell_indep(a_eq, structure, sc, sc, sc)
            # Apply uniaxial strain: stretch x by (1 + eps_xx)
            cell = np.diag([a_eq * sc * (1 + eps_xx), a_eq * sc, a_eq * sc])
            # Scale x-coordinates affinely
            positions[:, 0] *= 1 + eps_xx
            V0 = (a_eq * sc) ** 3
            e = _morse_energy_indep(positions, cell, D, alpha, r0, rc, pbc=True)
            return e / V0

        h = 1e-4
        e_plus = energy_density_uniaxial(h)
        e_minus = energy_density_uniaxial(-h)
        e_zero = energy_density_uniaxial(0.0)
        C11_ref = (e_plus - 2 * e_zero + e_minus) / h**2

        C11_solver = r["elastic_constants"]["C11"]
        rel_err = abs(C11_solver - C11_ref) / abs(C11_ref)
        assert rel_err < 0.01, (
            f"C11 mismatch: solver={C11_solver:.8e}, "
            f"independent={C11_ref:.8e}, rel_err={rel_err:.4e}"
        )


class TestBCCGenerality:
    """Test with BCC structure and different Morse parameters to prevent hardcoding."""

    BCC_POTENTIAL = {
        "type": "morse",
        "parameters": {"D": 0.4174, "alpha": 1.3885, "r0": 2.845, "cutoff": 4.5},
    }
    BCC_CONFIG = {
        "crystal_structure": "bcc",
        "element": "Fe",
        "approximate_lattice_constant": 3.2,
        "supercell_size": [3, 3, 3],
        "perturbation_amplitude": 0.04,
        "random_seed": 123,
    }

    @pytest.fixture(autouse=True, scope="class")
    def setup_bcc_and_run(self):
        """Save original config, write BCC config, run verifier, restore."""
        shutil.copy("/app/config.json", "/app/config_orig.json")
        shutil.copy("/app/potential_params.json", "/app/potential_params_orig.json")

        with open("/app/config.json", "w") as f:
            json.dump(self.BCC_CONFIG, f)
        with open("/app/potential_params.json", "w") as f:
            json.dump(self.BCC_POTENTIAL, f)

        result = subprocess.run(
            ["python3", "/app/elastic_verifier.py"],
            capture_output=True,
            text=True,
            timeout=600,
            cwd="/app",
        )
        assert result.returncode == 0, (
            f"BCC elastic_verifier.py failed:\nSTDOUT: {result.stdout[-500:]}\n"
            f"STDERR: {result.stderr[-500:]}"
        )

        yield

        shutil.move("/app/config_orig.json", "/app/config.json")
        shutil.move("/app/potential_params_orig.json", "/app/potential_params.json")

    def test_bcc_results_exist(self):
        assert os.path.exists("/app/results.json")

    def test_bcc_schema(self):
        r = read_results()
        assert "equilibrium_lattice_constant" in r
        ec = r["elastic_constants"]
        for key in ["C11", "C12", "C44", "bulk_modulus"]:
            assert key in ec

    def test_bcc_bulk_modulus_consistency(self):
        r = read_results()
        ec = r["elastic_constants"]
        B_computed = (ec["C11"] + 2 * ec["C12"]) / 3.0
        rel_err = abs(ec["bulk_modulus"] - B_computed) / abs(B_computed)
        assert rel_err < 1e-6, (
            f"BCC bulk modulus inconsistent: {ec['bulk_modulus']:.8e} vs {B_computed:.8e}"
        )

    def test_bcc_cauchy_relation(self):
        r = read_results()
        ec = r["elastic_constants"]
        denom = max(abs(ec["C12"]), abs(ec["C44"]), 1e-20)
        rel_diff = abs(ec["C12"] - ec["C44"]) / denom
        assert rel_diff < 0.06, (
            f"BCC Cauchy relation violated: C12={ec['C12']:.8e}, C44={ec['C44']:.8e}"
        )

    def test_bcc_physical_constraints(self):
        r = read_results()
        ec = r["elastic_constants"]
        assert ec["C11"] > 0
        assert ec["C44"] > 0
        assert ec["C11"] > abs(ec["C12"])
        assert ec["bulk_modulus"] > 0

    def test_bcc_force_grade(self):
        r = read_results()
        assert r["force_verification"]["grade"] in ("A", "B")

    def test_bcc_atom_count(self):
        """2x2x2 BCC cluster should have 16 atoms."""
        r = read_results()
        assert r["force_verification"]["num_atoms_tested"] == 16

    def test_bcc_lattice_constant_reasonable(self):
        r = read_results()
        a = r["equilibrium_lattice_constant"]
        assert 2.5 < a < 5.0, f"BCC lattice constant {a} outside reasonable range"

    def test_bcc_independent_lattice_constant(self):
        """Cross-validate BCC equilibrium lattice constant."""
        D = self.BCC_POTENTIAL["parameters"]["D"]
        alpha = self.BCC_POTENTIAL["parameters"]["alpha"]
        r0 = self.BCC_POTENTIAL["parameters"]["r0"]
        rc = self.BCC_POTENTIAL["parameters"]["cutoff"]

        def energy_per_atom(a):
            positions, cell = _build_supercell_indep(a, "bcc", 3, 3, 3)
            e = _morse_energy_indep(positions, cell, D, alpha, r0, rc, pbc=True)
            return e / len(positions)

        res = minimize_scalar(
            energy_per_atom, bounds=(2.5, 5.0), method="bounded",
            options={"xatol": 1e-12}
        )
        a_eq_ref = res.x

        r = read_results()
        a_eq = r["equilibrium_lattice_constant"]
        rel_err = abs(a_eq - a_eq_ref) / a_eq_ref
        assert rel_err < 1e-4, (
            f"BCC lattice constant mismatch: solver={a_eq:.8f}, "
            f"independent={a_eq_ref:.8f}"
        )
