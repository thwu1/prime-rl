"""
Tests for the E5 stiff ODE work-precision analysis task.

"""

import pytest
import os
import json
import csv
import importlib.util
import numpy as np

# E5 reference values from Hairer & Wanner Geneva Test Set (res_exact_pic)
# Computed to 19+ significant digits with high-order implicit RK
# Output times: 10, 1e3, 1e5, 1e7, 1e9, 1e11, 1e13
REFERENCE = {
    10.0: [1.7599259497677897058e-3, 1.3846281519376516449e-11,
           7.6370038530073911180e-13, 1.3082581134075777338e-11],
    1e3:  [1.6180769999072942552e-3, 1.3822370304983735443e-10,
           8.2515735006838336088e-12, 1.2997212954915352082e-10],
    1e5:  [7.4813208224292220114e-6, 2.3734781561205975019e-12,
           2.2123586689581663654e-12, 1.6111948716243113653e-13],
    1e7:  [4.7150333630401632232e-10, 1.8188895860807021729e-14,
           1.8188812376786725407e-14, 8.3484020296321693074e-20],
    1e9:  [3.1317148329356996037e-14, 1.4840957952870064294e-16,
           1.4840957948345691466e-16, 4.5243728279782625194e-26],
    1e11: [3.8139035189787091771e-49, 1.0192582567660293322e-20,
           1.0192582567660293322e-20, 3.7844935507486221171e-65],
    1e13: [0.0, 8.8612334976263783420e-23,
           8.8612334976263783421e-23, 0.0],
}

# E5 rate constants
K1 = 7.89e-10
K2 = 1.1e7
K3 = 1.13e9
K4 = 1.13e3

OUTPUT_TIMES = [10.0, 1e3, 1e5, 1e7, 1e9, 1e11, 1e13]


def e5_jacobian(y):
    """Reference Jacobian computation for verification."""
    J = np.zeros((4, 4))
    J[0, 0] = -K1 - K2 * y[2]
    J[0, 2] = -K2 * y[0]
    J[1, 0] = K1
    J[1, 1] = -K3 * y[2]
    J[1, 2] = -K3 * y[1]
    J[2, 0] = K1 - K2 * y[2]
    J[2, 1] = -K3 * y[2]
    J[2, 2] = -K2 * y[0] - K3 * y[1]
    J[2, 3] = K4
    J[3, 0] = K2 * y[2]
    J[3, 2] = K2 * y[0]
    J[3, 3] = -K4
    return J


def significant_correct_digits(computed, reference):
    """Compute number of significant correct digits."""
    if reference == 0.0:
        return 16.0 if computed == 0.0 else 0.0
    if abs(reference) < 1e-30:
        if abs(computed) < 1e-25:
            return 4.0
        return 0.0
    rel_err = abs(computed - reference) / abs(reference)
    if rel_err == 0.0:
        return 16.0
    return max(0.0, -np.log10(rel_err))


def parse_eigenvalue(val):
    """Parse an eigenvalue from JSON (could be float, str, or list)."""
    if isinstance(val, (int, float)):
        return complex(val)
    if isinstance(val, str):
        s = val.strip().strip('()')
        return complex(s.replace(' ', ''))
    if isinstance(val, list) and len(val) == 2:
        return complex(val[0], val[1])
    return complex(val)


class TestFortranReference:
    """Verify Fortran RADAU5 was compiled, run, and produced correct results."""

    def test_csv_exists(self):
        assert os.path.exists('/app/fortran_reference.csv'), \
            "fortran_reference.csv not found — Fortran compilation/execution failed"

    def test_csv_has_seven_rows(self):
        with open('/app/fortran_reference.csv') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 7, f"Expected 7 output times, got {len(rows)}"

    def test_csv_has_required_columns(self):
        with open('/app/fortran_reference.csv') as f:
            reader = csv.DictReader(f)
            cols = reader.fieldnames
        for c in ['t', 'y1', 'y2', 'y3', 'y4']:
            assert c in cols, f"Missing column '{c}' in fortran_reference.csv"

    def test_fortran_accuracy_at_t10(self):
        """Fortran output must match reference at t=10 to 4+ SCD."""
        with open('/app/fortran_reference.csv') as f:
            reader = csv.DictReader(f)
            rows_by_t = {}
            for row in reader:
                t = float(row['t'])
                rows_by_t[t] = row

        t = 10.0
        best_t = min(rows_by_t.keys(), key=lambda k: abs(k - t) / max(t, 1e-30))
        assert abs(best_t - t) / t < 0.01, \
            f"No row matching t={t} in fortran_reference.csv"
        row = rows_by_t[best_t]
        ref = REFERENCE[t]
        for i, col in enumerate(['y1', 'y2', 'y3', 'y4']):
            computed = float(row[col])
            if abs(ref[i]) > 1e-15:
                scd = significant_correct_digits(computed, ref[i])
                assert scd >= 4, \
                    f"Fortran at t={t}, {col}: {scd:.1f} SCD < 4 " \
                    f"(computed={computed}, ref={ref[i]})"

    def test_fortran_accuracy_at_t1000(self):
        """Fortran output must match reference at t=1000 to 4+ SCD."""
        with open('/app/fortran_reference.csv') as f:
            reader = csv.DictReader(f)
            rows_by_t = {}
            for row in reader:
                t = float(row['t'])
                rows_by_t[t] = row

        t = 1e3
        best_t = min(rows_by_t.keys(), key=lambda k: abs(k - t) / max(t, 1e-30))
        assert abs(best_t - t) / t < 0.01, \
            f"No row matching t={t} in fortran_reference.csv"
        row = rows_by_t[best_t]
        ref = REFERENCE[t]
        for i, col in enumerate(['y1', 'y2', 'y3', 'y4']):
            computed = float(row[col])
            if abs(ref[i]) > 1e-15:
                scd = significant_correct_digits(computed, ref[i])
                assert scd >= 4, \
                    f"Fortran at t={t}, {col}: {scd:.1f} SCD < 4 " \
                    f"(computed={computed}, ref={ref[i]})"


class TestPythonSolverModule:
    """Verify e5_solver.py structure and correctness."""

    def test_module_exists(self):
        assert os.path.exists('/app/e5_solver.py'), "e5_solver.py not found"

    def test_has_analytical_jacobian(self):
        """e5_solver.py must contain analytical Jacobian with E5 rate constants."""
        with open('/app/e5_solver.py') as f:
            code = f.read()
        has_k1 = '7.89' in code
        has_k2 = '1.1e' in code or '1.1E' in code or '11000000' in code
        has_k3 = '1.13e' in code or '1.13E' in code or '1130000000' in code
        assert has_k1 and (has_k2 or has_k3), \
            "e5_solver.py must implement analytical Jacobian with E5 rate constants"
        assert 'jac' in code.lower(), \
            "e5_solver.py must define a Jacobian function"

    def test_has_solve_function(self):
        """e5_solver.py must export solve_e5(method, rtol)."""
        spec = importlib.util.spec_from_file_location("e5_solver", "/app/e5_solver.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, 'solve_e5'), \
            "e5_solver.py must define solve_e5(method, rtol)"

    def test_rhs_function_correctness(self):
        """The E5 RHS function must produce correct values at a test state."""
        spec = importlib.util.spec_from_file_location("e5_solver", "/app/e5_solver.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Find the RHS function (common names)
        rhs_func = None
        for name in ['e5_rhs', 'rhs', 'f_e5', 'f', 'dydt']:
            if hasattr(mod, name):
                rhs_func = getattr(mod, name)
                break
        assert rhs_func is not None, \
            "e5_solver.py must define a RHS function (e5_rhs, rhs, f_e5, f, or dydt)"

        # Test at a non-trivial state
        y_test = np.array([1e-3, 1e-10, 5e-12, 8e-11])
        f = np.array(rhs_func(0.0, y_test))

        # Expected values (computed from E5 equations)
        prod1 = K1 * y_test[0]   # 7.89e-13
        prod2 = K2 * y_test[0] * y_test[2]   # 5.5e-8
        prod3 = K3 * y_test[1] * y_test[2]   # 5.65e-13
        prod4 = K4 * y_test[3]   # 9.04e-8
        f_expected = np.array([
            -prod1 - prod2,
            prod1 - prod3,
            (prod1 - prod3) - (prod2 - prod4),
            prod2 - prod4
        ])

        for i in range(4):
            if abs(f_expected[i]) > 1e-30:
                rel_err = abs(f[i] - f_expected[i]) / abs(f_expected[i])
                assert rel_err < 1e-10, \
                    f"RHS f[{i}]: expected {f_expected[i]:.6e}, got {f[i]:.6e}"

    def test_jacobian_function_correctness(self):
        """The E5 Jacobian function must produce correct values."""
        spec = importlib.util.spec_from_file_location("e5_solver", "/app/e5_solver.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Find the Jacobian function
        jac_func = None
        for name in ['e5_jac', 'jac', 'jacobian', 'jac_e5', 'e5_jacobian']:
            if hasattr(mod, name):
                jac_func = getattr(mod, name)
                break
        assert jac_func is not None, \
            "e5_solver.py must define a Jacobian function"

        y_test = np.array([1e-3, 1e-10, 5e-12, 8e-11])
        J = np.array(jac_func(0.0, y_test))

        # Expected Jacobian entries
        J_expected = e5_jacobian(y_test)

        for i in range(4):
            for j in range(4):
                exp_val = J_expected[i, j]
                got_val = J[i, j]
                if abs(exp_val) > 1e-30:
                    rel_err = abs(got_val - exp_val) / abs(exp_val)
                    assert rel_err < 1e-10, \
                        f"Jacobian J[{i},{j}]: expected {exp_val:.6e}, got {got_val:.6e}"
                else:
                    assert abs(got_val) < 1e-20, \
                        f"Jacobian J[{i},{j}]: expected ~0, got {got_val:.6e}"

    def test_short_radau_integration(self):
        """Quick integration test: Radau from t=0 to t=10 only."""
        from scipy.integrate import solve_ivp

        spec = importlib.util.spec_from_file_location("e5_solver", "/app/e5_solver.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Find RHS and Jacobian
        rhs_func = getattr(mod, 'e5_rhs', None) or getattr(mod, 'rhs', None)
        jac_func = getattr(mod, 'e5_jac', None) or getattr(mod, 'jac', None)
        assert rhs_func is not None, "Need RHS function for integration test"
        assert jac_func is not None, "Need Jacobian function for integration test"

        y0 = np.array([1.76e-3, 0.0, 0.0, 0.0])
        sol = solve_ivp(rhs_func, [0.0, 10.0], y0,
                        method='Radau', rtol=1e-6, atol=1e-18,
                        jac=jac_func, first_step=1e-6)
        assert sol.success, f"Integration failed: {sol.message}"

        y_end = sol.y[:, -1]
        ref = REFERENCE[10.0]
        for i in range(4):
            if abs(ref[i]) > 1e-15:
                scd = significant_correct_digits(y_end[i], ref[i])
                assert scd >= 3, \
                    f"Short integration y[{i+1}](t=10): {scd:.1f} SCD < 3 " \
                    f"(computed={y_end[i]:.6e}, ref={ref[i]:.6e})"


class TestPythonResultsCSV:
    """Verify python_results.csv format and completeness."""

    def test_csv_exists(self):
        assert os.path.exists('/app/python_results.csv'), \
            "python_results.csv not found"

    def test_csv_columns(self):
        with open('/app/python_results.csv') as f:
            reader = csv.DictReader(f)
            cols = reader.fieldnames
        for c in ['method', 'rtol', 't', 'y1', 'y2', 'y3', 'y4']:
            assert c in cols, f"Missing column '{c}'"

    def test_all_method_tolerance_combos_present(self):
        """All 8 method x tolerance combinations must appear."""
        combos = set()
        with open('/app/python_results.csv') as f:
            reader = csv.DictReader(f)
            for row in reader:
                method = row['method']
                rtol = float(row['rtol'])
                for target in [1e-4, 1e-6, 1e-8, 1e-10]:
                    if abs(np.log10(rtol) - np.log10(target)) < 0.5:
                        combos.add((method, target))
                        break
        expected = {('Radau', 1e-4), ('Radau', 1e-6), ('Radau', 1e-8), ('Radau', 1e-10),
                    ('BDF', 1e-4), ('BDF', 1e-6), ('BDF', 1e-8), ('BDF', 1e-10)}
        missing = expected - combos
        assert len(missing) == 0, f"Missing method/rtol combos: {missing}"

    def test_csv_has_enough_rows(self):
        """Should have at least 7 rows per combo (7 output times x 8 combos = 56)."""
        with open('/app/python_results.csv') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) >= 40, \
            f"Expected at least 40 rows (ideally 56), got {len(rows)}"


class TestEigenvalues:
    """Verify eigenvalue analysis."""

    def test_file_exists(self):
        assert os.path.exists('/app/eigenvalues.json'), \
            "eigenvalues.json not found"

    def test_required_keys(self):
        with open('/app/eigenvalues.json') as f:
            data = json.load(f)
        for key in ['eigenvalues_t0', 'eigenvalues_t10',
                     'stiffness_ratio_t0', 'stiffness_ratio_t10']:
            assert key in data, f"Missing key '{key}' in eigenvalues.json"

    def test_four_eigenvalues_each(self):
        with open('/app/eigenvalues.json') as f:
            data = json.load(f)
        assert len(data['eigenvalues_t0']) == 4, \
            f"Expected 4 eigenvalues at t=0, got {len(data['eigenvalues_t0'])}"
        assert len(data['eigenvalues_t10']) == 4, \
            f"Expected 4 eigenvalues at t=10, got {len(data['eigenvalues_t10'])}"

    def test_eigenvalue_magnitudes_t0(self):
        """Largest eigenvalue at t=0 should be > 1e3 (fast chemical mode)."""
        with open('/app/eigenvalues.json') as f:
            data = json.load(f)
        eigs = [parse_eigenvalue(e) for e in data['eigenvalues_t0']]
        mags = sorted([abs(e) for e in eigs])
        assert mags[-1] > 1e3, \
            f"Largest eigenvalue magnitude at t=0 is {mags[-1]}, expected > 1e3"

    def test_stiffness_ratio_t0(self):
        """Stiffness ratio at t=0 must be large (stiff system)."""
        with open('/app/eigenvalues.json') as f:
            data = json.load(f)
        ratio = float(data['stiffness_ratio_t0'])
        assert ratio > 1e6, \
            f"Stiffness ratio at t=0 is {ratio:.2e}, expected > 1e6"

    def test_eigenvalues_t10_reasonable(self):
        """Eigenvalues at t=10 should match independent computation."""
        with open('/app/eigenvalues.json') as f:
            data = json.load(f)
        computed_eigs = [parse_eigenvalue(e) for e in data['eigenvalues_t10']]
        computed_mags = sorted([abs(e) for e in computed_eigs])

        y_t10 = np.array(REFERENCE[10.0])
        J = e5_jacobian(y_t10)
        ref_eigs = np.linalg.eigvals(J)
        ref_mags = sorted([abs(e) for e in ref_eigs])

        # Largest eigenvalue magnitudes should agree to within 50%
        for exp, comp in zip(ref_mags[-2:], computed_mags[-2:]):
            if exp > 1e-10:
                rel_err = abs(comp - exp) / exp
                assert rel_err < 0.5, \
                    f"Eigenvalue magnitude mismatch: ref={exp:.4e}, got={comp:.4e}"
