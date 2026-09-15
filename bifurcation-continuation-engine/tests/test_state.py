"""
Verification tests for bifurcation analysis results.

Tests check: C library compilation and correctness, JSON structure,
equilibrium conditions, eigenvalue conditions, bifurcation counts,
analytical reference values, sub/supercritical classification,
and gnuplot diagram generation.
"""


import json
import os
import sys
import ctypes
from ctypes import c_int, c_double, POINTER
import pytest
import numpy as np

sys.path.insert(0, "/app")
from systems import SYSTEMS


@pytest.fixture(scope="session")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


# ---- C library tests ----

class TestCLibrary:
    def test_librhs_exists(self):
        assert os.path.isfile("/app/librhs.so"), "librhs.so not found"

    def test_librhs_loadable_and_count(self):
        lib = ctypes.CDLL("/app/librhs.so")
        lib.get_system_count.argtypes = []
        lib.get_system_count.restype = c_int
        assert lib.get_system_count() == 3, "get_system_count() != 3"

    def test_cusp_rhs_via_ctypes(self):
        lib = ctypes.CDLL("/app/librhs.so")
        lib.cusp_rhs.argtypes = [c_int, POINTER(c_double), c_double,
                                  POINTER(c_double)]
        lib.cusp_rhs.restype = None
        x = (c_double * 1)(0.5)
        out = (c_double * 1)(0.0)
        lib.cusp_rhs(1, x, c_double(0.0), out)
        # f = 0 + 0.5 - 0.125 = 0.375
        assert abs(out[0] - 0.375) < 1e-10, (
            f"cusp_rhs(0.5, 0) = {out[0]}, expected 0.375"
        )

    def test_brusselator_rhs_via_ctypes(self):
        lib = ctypes.CDLL("/app/librhs.so")
        lib.brusselator_rhs.argtypes = [c_int, POINTER(c_double), c_double,
                                         POINTER(c_double)]
        lib.brusselator_rhs.restype = None
        # At equilibrium (A, B/A) = (1.5, 2.0) with B=3.0
        x = (c_double * 2)(1.5, 2.0)
        out = (c_double * 2)(0.0, 0.0)
        lib.brusselator_rhs(2, x, c_double(3.0), out)
        assert abs(out[0]) < 1e-10, (
            f"brusselator at equilibrium f0={out[0]}"
        )
        assert abs(out[1]) < 1e-10, (
            f"brusselator at equilibrium f1={out[1]}"
        )

    def test_abc_rhs_via_ctypes(self):
        lib = ctypes.CDLL("/app/librhs.so")
        lib.abc_rhs.argtypes = [c_int, POINTER(c_double), c_double,
                                 POINTER(c_double)]
        lib.abc_rhs.restype = None
        x_py = SYSTEMS["abc_reaction"]["initial_state"]
        p_val = SYSTEMS["abc_reaction"]["initial_param"]
        x = (c_double * 3)(*x_py)
        out = (c_double * 3)(0.0, 0.0, 0.0)
        lib.abc_rhs(3, x, c_double(p_val), out)
        py_out = SYSTEMS["abc_reaction"]["rhs"](x_py, p_val)
        for i in range(3):
            assert abs(out[i] - py_out[i]) < 1e-8, (
                f"abc_rhs mismatch idx {i}: C={out[i]}, Py={py_out[i]}"
            )


# ---- Diagram and data file tests ----

class TestDiagram:
    def test_png_exists(self):
        assert os.path.isfile("/app/bifurcation_diagram.png"), (
            "bifurcation_diagram.png not found"
        )

    def test_png_valid_header(self):
        with open("/app/bifurcation_diagram.png", "rb") as f:
            header = f.read(8)
        assert header[:4] == b'\x89PNG', "Invalid PNG header"

    def test_gnuplot_script_exists(self):
        assert os.path.isfile("/app/plot_bifurcation.gp"), (
            "gnuplot script not found"
        )

    def test_dat_exists(self):
        assert os.path.isfile("/app/continuation_data.dat"), (
            "continuation_data.dat not found"
        )

    def test_dat_has_all_systems(self):
        with open("/app/continuation_data.dat") as f:
            content = f.read()
        for name in ["cusp_normal_form", "brusselator", "abc_reaction"]:
            assert name in content, (
                f"Missing {name} in continuation_data.dat"
            )

    def test_dat_has_bifurcation_markers(self):
        with open("/app/continuation_data.dat") as f:
            lines = f.readlines()
        point_types = set()
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 4:
                point_types.add(parts[3])
        assert "fold" in point_types, "No fold markers in continuation data"
        assert "hopf" in point_types, "No hopf markers in continuation data"


# ---- structure ----

class TestStructure:
    def test_all_systems_present(self, results):
        for name in ["cusp_normal_form", "brusselator", "abc_reaction"]:
            assert name in results, f"Missing system key: {name}"

    def test_keys_per_system(self, results):
        for name, data in results.items():
            assert "fold_points" in data, f"{name}: missing fold_points"
            assert "hopf_points" in data, f"{name}: missing hopf_points"
            assert isinstance(data["fold_points"], list)
            assert isinstance(data["hopf_points"], list)

    def test_fold_point_schema(self, results):
        for name, data in results.items():
            for fp in data["fold_points"]:
                assert "parameter_value" in fp, f"{name}: fold missing parameter_value"
                assert "state" in fp, f"{name}: fold missing state"
                assert isinstance(fp["parameter_value"], (int, float))
                assert isinstance(fp["state"], list)
                assert len(fp["state"]) == SYSTEMS[name]["dim"]

    def test_hopf_point_schema(self, results):
        for name, data in results.items():
            for hp in data["hopf_points"]:
                assert "parameter_value" in hp, f"{name}: hopf missing parameter_value"
                assert "state" in hp, f"{name}: hopf missing state"
                assert "omega" in hp, f"{name}: hopf missing omega"
                assert "subcritical" in hp, f"{name}: hopf missing subcritical"
                assert isinstance(hp["parameter_value"], (int, float))
                assert isinstance(hp["state"], list)
                assert isinstance(hp["omega"], (int, float))
                assert isinstance(hp["subcritical"], bool)
                assert len(hp["state"]) == SYSTEMS[name]["dim"]


# ---- equilibrium conditions ----

class TestEquilibrium:
    def test_fold_equilibria(self, results):
        for name, data in results.items():
            sys_def = SYSTEMS[name]
            for fp in data["fold_points"]:
                x = np.array(fp["state"])
                p = fp["parameter_value"]
                f = sys_def["rhs"](x, p)
                norm = np.linalg.norm(f)
                assert norm < 1e-4, (
                    f"{name}: fold at p={p:.6f} has ||f||={norm:.2e}"
                )

    def test_hopf_equilibria(self, results):
        for name, data in results.items():
            sys_def = SYSTEMS[name]
            for hp in data["hopf_points"]:
                x = np.array(hp["state"])
                p = hp["parameter_value"]
                f = sys_def["rhs"](x, p)
                norm = np.linalg.norm(f)
                assert norm < 1e-4, (
                    f"{name}: hopf at p={p:.6f} has ||f||={norm:.2e}"
                )


# ---- eigenvalue conditions ----

class TestEigenvalues:
    def test_fold_eigenvalues(self, results):
        for name, data in results.items():
            sys_def = SYSTEMS[name]
            for fp in data["fold_points"]:
                x = np.array(fp["state"])
                p = fp["parameter_value"]
                J = sys_def["jacobian"](x, p)
                eigs = np.linalg.eigvals(J)
                real_eigs = [e for e in eigs if abs(e.imag) < 0.2]
                min_abs = min(abs(e.real) for e in real_eigs) if real_eigs else 999.0
                assert min_abs < 0.05, (
                    f"{name}: fold at p={p:.6f} min|real eig|={min_abs:.4f}"
                )

    def test_hopf_eigenvalues(self, results):
        for name, data in results.items():
            sys_def = SYSTEMS[name]
            for hp in data["hopf_points"]:
                x = np.array(hp["state"])
                p = hp["parameter_value"]
                J = sys_def["jacobian"](x, p)
                eigs = np.linalg.eigvals(J)
                cpx = [e for e in eigs if abs(e.imag) > 0.01]
                assert len(cpx) >= 2, (
                    f"{name}: hopf at p={p:.6f} has no complex pair"
                )
                min_re = min(abs(e.real) for e in cpx)
                assert min_re < 0.05, (
                    f"{name}: hopf at p={p:.6f} |Re(λ)|={min_re:.4f}"
                )

    def test_hopf_omega_consistent(self, results):
        for name, data in results.items():
            sys_def = SYSTEMS[name]
            for hp in data["hopf_points"]:
                x = np.array(hp["state"])
                p = hp["parameter_value"]
                J = sys_def["jacobian"](x, p)
                eigs = np.linalg.eigvals(J)
                cpx = [e for e in eigs if abs(e.imag) > 0.01]
                if not cpx:
                    continue
                best = min(cpx, key=lambda e: abs(e.real))
                expected_omega = abs(best.imag)
                reported = hp["omega"]
                assert reported > 0, f"{name}: omega must be positive"
                rel_err = abs(reported - expected_omega) / expected_omega
                assert rel_err < 0.10, (
                    f"{name}: omega={reported:.4f}, expected~{expected_omega:.4f}"
                )


# ---- cusp_normal_form specifics ----

class TestCusp:
    def test_fold_count(self, results):
        cusp = results["cusp_normal_form"]
        assert len(cusp["fold_points"]) == 2, (
            f"Expected 2 folds, got {len(cusp['fold_points'])}"
        )

    def test_no_hopf(self, results):
        cusp = results["cusp_normal_form"]
        assert len(cusp["hopf_points"]) == 0, (
            f"Expected 0 hopf, got {len(cusp['hopf_points'])}"
        )

    def test_fold_parameter_values(self, results):
        cusp = results["cusp_normal_form"]
        expected = sorted([-2.0 * np.sqrt(3) / 9.0, 2.0 * np.sqrt(3) / 9.0])
        found = sorted(fp["parameter_value"] for fp in cusp["fold_points"])
        for exp, fnd in zip(expected, found):
            assert abs(exp - fnd) < 0.01, (
                f"Fold mu={fnd:.6f}, expected {exp:.6f}"
            )

    def test_fold_states(self, results):
        cusp = results["cusp_normal_form"]
        expected_x = sorted([-1.0 / np.sqrt(3), 1.0 / np.sqrt(3)])
        found_x = sorted(fp["state"][0] for fp in cusp["fold_points"])
        for exp, fnd in zip(expected_x, found_x):
            assert abs(exp - fnd) < 0.02, (
                f"Fold state x={fnd:.6f}, expected {exp:.6f}"
            )


# ---- brusselator specifics ----

class TestBrusselator:
    def test_no_folds(self, results):
        brus = results["brusselator"]
        assert len(brus["fold_points"]) == 0, (
            f"Expected 0 folds, got {len(brus['fold_points'])}"
        )

    def test_hopf_present(self, results):
        brus = results["brusselator"]
        assert len(brus["hopf_points"]) >= 1, (
            f"Expected >=1 hopf, got {len(brus['hopf_points'])}"
        )

    def test_hopf_parameter(self, results):
        brus = results["brusselator"]
        expected_B = 1.0 + 1.5**2  # 3.25
        params = [hp["parameter_value"] for hp in brus["hopf_points"]]
        closest = min(params, key=lambda p: abs(p - expected_B))
        assert abs(closest - expected_B) < 0.02, (
            f"Hopf at B={closest:.6f}, expected {expected_B}"
        )

    def test_hopf_omega(self, results):
        brus = results["brusselator"]
        expected_omega = 1.5
        for hp in brus["hopf_points"]:
            if abs(hp["parameter_value"] - 3.25) < 0.1:
                rel_err = abs(hp["omega"] - expected_omega) / expected_omega
                assert rel_err < 0.10, (
                    f"omega={hp['omega']:.4f}, expected {expected_omega}"
                )

    def test_hopf_supercritical(self, results):
        brus = results["brusselator"]
        for hp in brus["hopf_points"]:
            if abs(hp["parameter_value"] - 3.25) < 0.1:
                assert hp["subcritical"] is False, (
                    "Brusselator Hopf should be supercritical"
                )

    def test_hopf_state(self, results):
        brus = results["brusselator"]
        for hp in brus["hopf_points"]:
            if abs(hp["parameter_value"] - 3.25) < 0.1:
                x = hp["state"]
                assert abs(x[0] - 1.5) < 0.05, f"x={x[0]}, expected 1.5"
                assert abs(x[1] - 3.25 / 1.5) < 0.05, (
                    f"y={x[1]}, expected {3.25/1.5:.4f}"
                )


# ---- abc_reaction specifics ----

class TestABCReaction:
    def test_hopf_present(self, results):
        abc = results["abc_reaction"]
        assert len(abc["hopf_points"]) >= 1, (
            f"Expected >=1 hopf, got {len(abc['hopf_points'])}"
        )

    def test_hopf_in_param_range(self, results):
        abc = results["abc_reaction"]
        prange = SYSTEMS["abc_reaction"]["param_range"]
        for hp in abc["hopf_points"]:
            p = hp["parameter_value"]
            assert prange[0] - 0.1 <= p <= prange[1] + 0.1, (
                f"Hopf p1={p:.4f} outside range {prange}"
            )

    def test_hopf_omega_positive(self, results):
        abc = results["abc_reaction"]
        for hp in abc["hopf_points"]:
            assert hp["omega"] > 0, "omega must be positive"

    def test_hopf_subcritical_is_bool(self, results):
        abc = results["abc_reaction"]
        for hp in abc["hopf_points"]:
            assert isinstance(hp["subcritical"], bool)

    def test_hopf_equilibria_valid(self, results):
        abc = results["abc_reaction"]
        sys_def = SYSTEMS["abc_reaction"]
        for hp in abc["hopf_points"]:
            x = np.array(hp["state"])
            p = hp["parameter_value"]
            assert len(x) == 3
            f = sys_def["rhs"](x, p)
            assert np.linalg.norm(f) < 1e-4

    def test_hopf_eigenvalues_valid(self, results):
        abc = results["abc_reaction"]
        sys_def = SYSTEMS["abc_reaction"]
        for hp in abc["hopf_points"]:
            x = np.array(hp["state"])
            p = hp["parameter_value"]
            J = sys_def["jacobian"](x, p)
            eigs = np.linalg.eigvals(J)
            cpx = [e for e in eigs if abs(e.imag) > 0.01]
            assert len(cpx) >= 2, "No complex pair at Hopf"
            min_re = min(abs(e.real) for e in cpx)
            assert min_re < 0.05, f"|Re(λ)|={min_re:.4f}"

    def test_fold_equilibria_valid(self, results):
        abc = results["abc_reaction"]
        sys_def = SYSTEMS["abc_reaction"]
        for fp in abc["fold_points"]:
            x = np.array(fp["state"])
            p = fp["parameter_value"]
            assert len(x) == 3
            f = sys_def["rhs"](x, p)
            assert np.linalg.norm(f) < 1e-4
