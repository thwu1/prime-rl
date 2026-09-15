
import pytest
import sys
import os
import json
import subprocess
import numpy as np
from numpy import inf, pi

sys.path.insert(0, '/app')
from tmm_solver import coh_tmm, ellips, position_resolved, absorp_in_each_layer


def df(a, b):
    """Relative difference fraction."""
    return abs(a - b) / max(abs(a), abs(b), 1e-30)


# ====================================================================
# Test suite 1: Coherent TMM golden values (verified against Mathematica)
# ====================================================================

class TestCoherentTMMGoldenValues:
    """Compare coh_tmm output against Mathematica-verified reference values."""

    def setup_method(self):
        self.n_list = [1, 2 + 4j, 3 + 0.3j, 1 + 0.1j]
        self.d_list = [inf, 2, 3, inf]
        self.th_0 = 0.1
        self.lam_vac = 100

    def test_s_reflection_amplitude(self):
        s = coh_tmm('s', self.n_list, self.d_list, self.th_0, self.lam_vac)
        assert df(s['r'], -0.60331226568845775 - 0.093522181653632019j) < 1e-10

    def test_s_reflected_power(self):
        s = coh_tmm('s', self.n_list, self.d_list, self.th_0, self.lam_vac)
        assert df(s['R'], 0.37273208839139516) < 1e-10

    def test_s_transmitted_power(self):
        s = coh_tmm('s', self.n_list, self.d_list, self.th_0, self.lam_vac)
        assert df(s['T'], 0.22604491247079261) < 1e-10

    def test_p_reflection_amplitude(self):
        p = coh_tmm('p', self.n_list, self.d_list, self.th_0, self.lam_vac)
        assert df(p['r'], 0.60102654255772481 + 0.094489146845323682j) < 1e-10

    def test_p_reflected_power(self):
        p = coh_tmm('p', self.n_list, self.d_list, self.th_0, self.lam_vac)
        assert df(p['R'], 0.37016110373044969) < 1e-10

    def test_p_transmitted_power(self):
        p = coh_tmm('p', self.n_list, self.d_list, self.th_0, self.lam_vac)
        assert df(p['T'], 0.22824374314132009) < 1e-10

    def test_kz_list_value(self):
        n_list2 = [1, 2.2 + 0.2j, 3.3 + 0.3j, 1]
        d_list2 = [inf, 100, 300, inf]
        cd = coh_tmm('p', n_list2, d_list2, pi / 4, 400)
        assert df(cd['kz_list'][1],
                  0.0327410685922732 + 0.003315885921866465j) < 1e-10


# ====================================================================
# Test suite 2: Ellipsometric parameters
# ====================================================================

class TestEllipsometry:
    def test_psi_value(self):
        n_list = [1, 2 + 4j, 3 + 0.3j, 1 + 0.1j]
        d_list = [inf, 2, 3, inf]
        e = ellips(n_list, d_list, 0.1, 100)
        assert df(e['psi'], 0.78366777347038352) < 1e-10

    def test_delta_value(self):
        n_list = [1, 2 + 4j, 3 + 0.3j, 1 + 0.1j]
        d_list = [inf, 2, 3, inf]
        e = ellips(n_list, d_list, 0.1, 100)
        assert df(e['Delta'], 0.0021460774404193292) < 1e-10


# ====================================================================
# Test suite 3: Position-resolved Poynting vector and absorption
# ====================================================================

class TestPositionResolved:
    def setup_method(self):
        self.n_list = [1, 2.2 + 0.2j, 3.3 + 0.3j, 1]
        self.d_list = [inf, 100, 300, inf]
        self.th_0 = pi / 4
        self.lam_vac = 400

    def test_poynting_p_polarization(self):
        cd = coh_tmm('p', self.n_list, self.d_list, self.th_0, self.lam_vac)
        data = position_resolved(1, 37, cd)
        assert df(data['poyn'], 0.7094950598055798) < 1e-10

    def test_absorption_p_polarization(self):
        cd = coh_tmm('p', self.n_list, self.d_list, self.th_0, self.lam_vac)
        data = position_resolved(1, 37, cd)
        assert df(data['absor'], 0.005135049118053356) < 1e-10

    def test_poynting_s_polarization(self):
        cd = coh_tmm('s', self.n_list, self.d_list, self.th_0, self.lam_vac)
        data = position_resolved(1, 37, cd)
        assert df(data['poyn'], 0.5422594735025152) < 1e-10

    def test_absorption_s_polarization(self):
        cd = coh_tmm('s', self.n_list, self.d_list, self.th_0, self.lam_vac)
        data = position_resolved(1, 37, cd)
        assert df(data['absor'], 0.004041912286816303) < 1e-10


# ====================================================================
# Test suite 4: Energy conservation
# ====================================================================

class TestEnergyConservation:
    """Absorption in all layers must sum to 1."""

    def test_energy_conservation_s_polarization(self):
        n_list = [1, 2.2 + 0.2j, 3.3 + 0.3j, 1]
        d_list = [inf, 100, 300, inf]
        cd = coh_tmm('s', n_list, d_list, pi / 4, 400)
        assert abs(sum(absorp_in_each_layer(cd)) - 1.0) < 1e-10

    def test_energy_conservation_p_polarization(self):
        n_list = [1, 2.2 + 0.2j, 3.3 + 0.3j, 1]
        d_list = [inf, 100, 300, inf]
        cd = coh_tmm('p', n_list, d_list, pi / 4, 400)
        assert abs(sum(absorp_in_each_layer(cd)) - 1.0) < 1e-10

    def test_energy_conservation_absorptive_endpoints(self):
        """Complex refractive index in both first and last layers."""
        from numpy.lib.scimath import arcsin as complex_arcsin
        n00 = 1
        th00 = pi / 4
        n0 = 1 + 0.1j
        th_0_guess = complex_arcsin(n00 * np.sin(th00) / n0)
        ncosth = n0 * np.cos(th_0_guess)
        if abs(ncosth.imag) > 1e-10:
            if ncosth.imag < 0:
                th_0_guess = pi - th_0_guess
        else:
            if ncosth.real < 0:
                th_0_guess = pi - th_0_guess
        th_0 = th_0_guess

        n_list = [n0, 2.2 + 0.2j, 3.3 + 0.3j, 1 + 0.4j]
        d_list = [inf, 100, 300, inf]
        for pol in ['s', 'p']:
            cd = coh_tmm(pol, n_list, d_list, th_0, 400)
            total = sum(absorp_in_each_layer(cd))
            assert abs(total - 1.0) < 1e-10, \
                f"Energy not conserved for {pol}: sum={total}"

    def test_energy_conservation_five_layers(self):
        """Five-layer stack with mixed absorptive layers."""
        n_list = [1, 1.5 + 0.01j, 2.0 + 0.3j, 1.8, 1]
        d_list = [inf, 200, 50, 300, inf]
        for pol in ['s', 'p']:
            cd = coh_tmm(pol, n_list, d_list, 0.3, 550)
            total = sum(absorp_in_each_layer(cd))
            assert abs(total - 1.0) < 1e-10, \
                f"Energy not conserved for 5-layer {pol}: sum={total}"


# ====================================================================
# Test suite 5: Poynting vector continuity at interfaces
# ====================================================================

class TestPoyntingContinuity:
    def test_continuity_at_layer_boundary(self):
        n_list = [1, 2.2 + 0.2j, 3.3 + 0.3j, 1]
        d_list = [inf, 100, 300, inf]
        for pol in ['s', 'p']:
            cd = coh_tmm(pol, n_list, d_list, pi / 4, 400)
            # End of layer 1
            p1 = position_resolved(1, 100, cd)['poyn']
            # Start of layer 2
            p2 = position_resolved(2, 0, cd)['poyn']
            assert abs(p1 - p2) < 1e-12, \
                f"Poynting discontinuity at interface 1->2 for {pol}: {abs(p1 - p2)}"

    def test_poynting_equals_power_entering(self):
        n_list = [1, 2.2 + 0.2j, 3.3 + 0.3j, 1]
        d_list = [inf, 100, 300, inf]
        for pol in ['s', 'p']:
            cd = coh_tmm(pol, n_list, d_list, pi / 4, 400)
            p_start = position_resolved(1, 0, cd)['poyn']
            assert df(p_start, cd['power_entering']) < 1e-10, \
                f"Poynting at layer 1 start != power_entering for {pol}"

    def test_poynting_equals_T_at_exit(self):
        n_list = [1, 2.2 + 0.2j, 3.3 + 0.3j, 1]
        d_list = [inf, 100, 300, inf]
        for pol in ['s', 'p']:
            cd = coh_tmm(pol, n_list, d_list, pi / 4, 400)
            p_end = position_resolved(2, 300, cd)['poyn']
            assert df(p_end, cd['T']) < 1e-10, \
                f"Poynting at last layer end != T for {pol}"


# ====================================================================
# Test suite 6: Absorption derivative consistency
# ====================================================================

class TestAbsorptionDerivative:
    """d(poyn)/dz should equal -absor."""

    def test_finite_difference_matches_absorption(self):
        n_list = [1, 2.2 + 0.2j, 3.3 + 0.3j, 1]
        d_list = [inf, 100, 300, inf]
        eps = 0.001
        for pol in ['s', 'p']:
            cd = coh_tmm(pol, n_list, d_list, pi / 4, 400)
            d1 = position_resolved(1, 37, cd)
            d2 = position_resolved(1, 37 + eps, cd)
            absor_avg = (d1['absor'] + d2['absor']) / 2
            poyn_deriv = (d1['poyn'] - d2['poyn']) / eps
            assert df(absor_avg, poyn_deriv) < 1e-4, \
                f"Derivative mismatch for {pol}: absor={absor_avg}, deriv={poyn_deriv}"


# ====================================================================
# Test suite 7: Numerical stability
# ====================================================================

class TestNumericalStability:
    def test_very_opaque_layer_no_nan(self):
        """Very opaque layer must not produce NaN or overflow."""
        n_list = [1., 2 + 0.1j, 1 + 3j, 4., 5.]
        d_list = [inf, 50, 1e5, 50, inf]
        data = coh_tmm('s', n_list, d_list, 0, 200)
        assert not np.isnan(data['R']), "R is NaN for opaque layer"
        assert not np.isnan(data['T']), "T is NaN for opaque layer"
        assert data['R'] >= 0, "R is negative"
        assert data['T'] >= 0, "T is negative"
        # T should be essentially zero for extremely opaque layer
        assert data['T'] < 1e-10, "T should be negligible for 1e5 nm of 1+3j"

    def test_opaque_layer_R_reasonable(self):
        """R should match what you get if the stack ends at the opaque layer."""
        n_list = [1., 2 + 0.1j, 1 + 3j, 4., 5.]
        d_list = [inf, 50, 1e5, 50, inf]
        data = coh_tmm('s', n_list, d_list, 0, 200)
        # Compare with truncated stack
        n_list2 = [1., 2 + 0.1j, 1 + 3j]
        d_list2 = [inf, 50, inf]
        data2 = coh_tmm('s', n_list2, d_list2, 0, 200)
        assert df(data['R'], data2['R']) < 1e-6, \
            "Opaque stack R should match truncated stack R"


# ====================================================================
# Test suite 8: Normal incidence s/p equivalence
# ====================================================================

class TestNormalIncidence:
    def test_s_p_equivalence_at_normal(self):
        """At normal incidence, s and p must give identical R and T."""
        n_list = [1, 2.0 + 0.1j, 3.0, 1]
        d_list = [inf, 150, 200, inf]
        s = coh_tmm('s', n_list, d_list, 0, 500)
        p = coh_tmm('p', n_list, d_list, 0, 500)
        assert df(s['R'], p['R']) < 1e-10, "R differs for s/p at normal incidence"
        assert df(s['T'], p['T']) < 1e-10, "T differs for s/p at normal incidence"


# ====================================================================
# Test suite 9: Single interface R+T=1
# ====================================================================

class TestSingleInterface:
    def test_RT_sum_for_real_ni(self):
        """When ni is real, R+T should equal 1 for a single interface."""
        from numpy.lib.scimath import arcsin as complex_arcsin
        ni = 2
        nf = 3. + 0.2j
        thi = pi / 5
        thf_guess = complex_arcsin(ni * np.sin(thi) / nf)
        ncosth = nf * np.cos(thf_guess)
        if abs(ncosth.imag) > 1e-10:
            if ncosth.imag < 0:
                thf_guess = pi - thf_guess
        else:
            if ncosth.real < 0:
                thf_guess = pi - thf_guess
        thf = thf_guess

        n_list = [ni, nf]
        d_list = [inf, inf]
        for pol in ['s', 'p']:
            cd = coh_tmm(pol, n_list, d_list, thi, 500)
            assert abs(cd['R'] + cd['T'] - 1.0) < 1e-10, \
                f"R+T != 1 for single interface {pol}: R={cd['R']}, T={cd['T']}"


# ====================================================================
# Test suite 10: Ellipsometry inverse problem fitting
# ====================================================================

class TestFittingResult:
    """Verify that the spectroscopic ellipsometry inversion recovers
    the ground-truth film parameters."""

    def test_results_file_exists(self):
        assert os.path.exists('/app/results.json'), \
            "/app/results.json not found — run_fit.py must produce this file"

    def test_thickness_recovery(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        assert 'thickness_nm' in results, "results.json missing 'thickness_nm'"
        assert abs(results['thickness_nm'] - 250.0) < 3.0, \
            f"Thickness {results['thickness_nm']:.4f} nm not within 3 nm of 250"

    def test_cauchy_A_recovery(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        assert 'cauchy_A' in results, "results.json missing 'cauchy_A'"
        assert abs(results['cauchy_A'] - 1.46) < 0.01, \
            f"Cauchy A = {results['cauchy_A']:.6f}, expected 1.46 ± 0.01"

    def test_cauchy_B_recovery(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        assert 'cauchy_B' in results, "results.json missing 'cauchy_B'"
        assert abs(results['cauchy_B'] - 5000.0) < 300.0, \
            f"Cauchy B = {results['cauchy_B']:.2f}, expected 5000 ± 300"

    def test_forward_model_residuals(self):
        """Verify that the fitted parameters reproduce the measurement data."""
        with open('/app/results.json') as f:
            results = json.load(f)
        import csv
        from scipy.interpolate import interp1d

        # Load Si optical constants
        si_wl, si_n, si_k = [], [], []
        with open('/app/si_nk.csv') as f:
            reader = csv.DictReader(f)
            for row in reader:
                si_wl.append(float(row['wavelength_nm']))
                si_n.append(float(row['n']))
                si_k.append(float(row['k']))
        si_n_fn = interp1d(si_wl, si_n, kind='cubic')
        si_k_fn = interp1d(si_wl, si_k, kind='cubic')

        d_fit = results['thickness_nm']
        A_fit = results['cauchy_A']
        B_fit = results['cauchy_B']

        degree = pi / 180
        max_residual = 0.0

        with open('/app/measurements.csv') as f:
            reader = csv.DictReader(f)
            for row in reader:
                lam = float(row['wavelength_nm'])
                ang = float(row['angle_deg'])
                psi_meas = float(row['psi_rad'])
                delta_meas = float(row['Delta_rad'])

                n_si = complex(float(si_n_fn(lam)), float(si_k_fn(lam)))
                n_film = A_fit + B_fit / lam ** 2
                n_list = [1, n_film, n_si]
                d_list = [inf, d_fit, inf]

                e = ellips(n_list, d_list, ang * degree, lam)
                res_psi = abs(e['psi'] - psi_meas)
                res_delta = abs(e['Delta'] - delta_meas)
                max_residual = max(max_residual, res_psi, res_delta)

        assert max_residual < 0.01, \
            f"Max residual {max_residual:.6f} rad exceeds 0.01 rad tolerance"


# ====================================================================
# Test suite 11: CLI compute subcommand
# ====================================================================

class TestCLICompute:
    """Verify /app/tmm_cli.sh compute reads JSON stdin, writes JSON stdout."""

    def test_cli_exists_and_executable(self):
        assert os.path.isfile('/app/tmm_cli.sh'), \
            "/app/tmm_cli.sh not found"
        assert os.access('/app/tmm_cli.sh', os.X_OK), \
            "/app/tmm_cli.sh is not executable"

    def test_compute_s_polarization(self):
        input_json = json.dumps({
            "pol": "s",
            "n_list": [1, [2, 4], [3, 0.3], [1, 0.1]],
            "d_list": ["inf", 2, 3, "inf"],
            "th_0": 0.1,
            "lam_vac": 100
        })
        result = subprocess.run(
            ['/app/tmm_cli.sh', 'compute'],
            input=input_json, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, \
            f"CLI compute failed (rc={result.returncode}): {result.stderr}"
        out = json.loads(result.stdout)
        assert 'R' in out and 'T' in out and 'r_real' in out and 'r_imag' in out, \
            f"Missing keys in output: {list(out.keys())}"
        assert df(out['R'], 0.37273208839139516) < 1e-8, \
            f"R mismatch: {out['R']}"
        assert df(out['T'], 0.22604491247079261) < 1e-8, \
            f"T mismatch: {out['T']}"

    def test_compute_p_polarization(self):
        input_json = json.dumps({
            "pol": "p",
            "n_list": [1, [2, 4], [3, 0.3], [1, 0.1]],
            "d_list": ["inf", 2, 3, "inf"],
            "th_0": 0.1,
            "lam_vac": 100
        })
        result = subprocess.run(
            ['/app/tmm_cli.sh', 'compute'],
            input=input_json, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, \
            f"CLI compute failed (rc={result.returncode}): {result.stderr}"
        out = json.loads(result.stdout)
        assert df(out['R'], 0.37016110373044969) < 1e-8, \
            f"R mismatch: {out['R']}"
        assert df(out['T'], 0.22824374314132009) < 1e-8, \
            f"T mismatch: {out['T']}"
        assert df(out['r_real'], 0.60102654255772481) < 1e-8, \
            f"r_real mismatch: {out['r_real']}"
        assert df(out['r_imag'], 0.094489146845323682) < 1e-8, \
            f"r_imag mismatch: {out['r_imag']}"


# ====================================================================
# Test suite 12: CLI sweep subcommand with SQLite output
# ====================================================================

class TestCLISweep:
    """Verify /app/tmm_cli.sh sweep populates SQLite database correctly."""

    @classmethod
    def setup_class(cls):
        """Run the sweep command to populate the database."""
        if os.path.exists('/app/sweep_results.db'):
            os.remove('/app/sweep_results.db')
        input_json = json.dumps({
            "n_list": [1, [2.2, 0.2], [3.3, 0.3], 1],
            "d_list": ["inf", 100, 300, "inf"],
            "th_0": 0.7853981633974483,
            "lam_min": 400,
            "lam_max": 800,
            "lam_count": 5
        })
        result = subprocess.run(
            ['/app/tmm_cli.sh', 'sweep'],
            input=input_json, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, \
            f"CLI sweep failed (rc={result.returncode}): {result.stderr}"

    def test_database_exists(self):
        assert os.path.exists('/app/sweep_results.db'), \
            "sweep_results.db not created by sweep command"

    def test_table_schema(self):
        import sqlite3
        conn = sqlite3.connect('/app/sweep_results.db')
        cursor = conn.execute("PRAGMA table_info(sweep)")
        cols = {row[1] for row in cursor.fetchall()}
        conn.close()
        expected = {'wavelength_nm', 'R_s', 'T_s', 'R_p', 'T_p'}
        assert cols == expected, \
            f"Wrong columns: {cols}, expected {expected}"

    def test_row_count(self):
        import sqlite3
        conn = sqlite3.connect('/app/sweep_results.db')
        cursor = conn.execute("SELECT COUNT(*) FROM sweep")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 5, f"Expected 5 rows, got {count}"

    def test_energy_conservation_in_sweep(self):
        """R+T <= 1 at each wavelength for real incident medium."""
        import sqlite3
        conn = sqlite3.connect('/app/sweep_results.db')
        cursor = conn.execute(
            "SELECT wavelength_nm, R_s, T_s, R_p, T_p FROM sweep")
        for row in cursor.fetchall():
            wl, rs, ts, rp, tp = row
            assert rs + ts <= 1.0 + 1e-10, \
                f"R_s+T_s > 1 at {wl} nm: {rs + ts}"
            assert rp + tp <= 1.0 + 1e-10, \
                f"R_p+T_p > 1 at {wl} nm: {rp + tp}"
            assert rs >= 0 and ts >= 0, \
                f"Negative R_s or T_s at {wl} nm"
            assert rp >= 0 and tp >= 0, \
                f"Negative R_p or T_p at {wl} nm"
        conn.close()

    def test_spot_check_against_direct_computation(self):
        """Cross-validate a specific wavelength against direct coh_tmm call."""
        import sqlite3
        conn = sqlite3.connect('/app/sweep_results.db')
        cursor = conn.execute(
            "SELECT R_s, T_s, R_p, T_p FROM sweep "
            "WHERE abs(wavelength_nm - 400.0) < 0.01")
        row = cursor.fetchone()
        conn.close()
        assert row is not None, "No row near wavelength_nm = 400.0"

        cd_s = coh_tmm('s', [1, 2.2 + 0.2j, 3.3 + 0.3j, 1],
                        [inf, 100, 300, inf], pi / 4, 400)
        cd_p = coh_tmm('p', [1, 2.2 + 0.2j, 3.3 + 0.3j, 1],
                        [inf, 100, 300, inf], pi / 4, 400)
        assert df(row[0], cd_s['R']) < 1e-8, \
            f"R_s mismatch at 400 nm: {row[0]} vs {cd_s['R']}"
        assert df(row[1], cd_s['T']) < 1e-8, \
            f"T_s mismatch at 400 nm: {row[1]} vs {cd_s['T']}"
        assert df(row[2], cd_p['R']) < 1e-8, \
            f"R_p mismatch at 400 nm: {row[2]} vs {cd_p['R']}"
        assert df(row[3], cd_p['T']) < 1e-8, \
            f"T_p mismatch at 400 nm: {row[3]} vs {cd_p['T']}"
