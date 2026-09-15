"""
Verification tests for compressible flow simulation pipeline output.
Tests check CSV result files, convergence study JSON, convergence plot,
SQLite results database, and Makefile pipeline integrity.

"""

import pytest
import os
import json
import sqlite3
import numpy as np


# -- Result files: existence and format --------------------------------------

class TestResultFiles:
    @pytest.mark.parametrize("name", ["sod", "einfeldt", "blast"])
    def test_csv_exists(self, name):
        path = f'/app/results/{name}.csv'
        assert os.path.exists(path), f"Result file {path} not found"

    @pytest.mark.parametrize("name", ["sod", "einfeldt", "blast"])
    def test_csv_format(self, name):
        data = np.genfromtxt(f'/app/results/{name}.csv', delimiter=',',
                             names=True)
        assert 'x' in data.dtype.names
        assert 'rho' in data.dtype.names
        assert 'u' in data.dtype.names
        assert 'p' in data.dtype.names
        assert len(data) >= 100, f"Expected >= 100 rows, got {len(data)}"


# -- Sod problem: accuracy ---------------------------------------------------

class TestSodAccuracy:
    @pytest.fixture
    def sod(self):
        return np.genfromtxt('/app/results/sod.csv', delimiter=',', names=True)

    def test_positivity(self, sod):
        assert np.all(sod['rho'] > 0), "Negative density found"
        assert np.all(sod['p'] > 0), "Negative pressure found"

    def test_undisturbed_left_density(self, sod):
        mask = sod['x'] < 0.15
        assert np.sum(mask) > 0
        err = np.mean(np.abs(sod['rho'][mask] - 1.0))
        assert err < 0.001, f"Left region density error = {err}"

    def test_undisturbed_right_density(self, sod):
        mask = sod['x'] > 0.96
        assert np.sum(mask) > 0
        err = np.mean(np.abs(sod['rho'][mask] - 0.125))
        assert err < 0.001, f"Right region density error = {err}"

    def test_star_left_density(self, sod):
        mask = (sod['x'] > 0.55) & (sod['x'] < 0.68)
        mean_rho = np.mean(sod['rho'][mask])
        assert abs(mean_rho - 0.42632) < 0.02, \
            f"Star-left density = {mean_rho}, expected ~0.426"

    def test_star_right_density(self, sod):
        mask = (sod['x'] > 0.76) & (sod['x'] < 0.90)
        mean_rho = np.mean(sod['rho'][mask])
        assert abs(mean_rho - 0.26557) < 0.02, \
            f"Star-right density = {mean_rho}, expected ~0.266"

    def test_star_velocity(self, sod):
        mask = (sod['x'] > 0.55) & (sod['x'] < 0.90)
        mean_u = np.mean(sod['u'][mask])
        assert abs(mean_u - 0.92745) < 0.03, \
            f"Star velocity = {mean_u}, expected ~0.927"

    def test_star_pressure(self, sod):
        mask = (sod['x'] > 0.55) & (sod['x'] < 0.90)
        mean_p = np.mean(sod['p'][mask])
        assert abs(mean_p - 0.30313) < 0.02, \
            f"Star pressure = {mean_p}, expected ~0.303"


# -- Sod problem: conservation -----------------------------------------------

class TestSodConservation:
    @pytest.fixture
    def sod(self):
        return np.genfromtxt('/app/results/sod.csv', delimiter=',', names=True)

    def test_mass_conservation(self, sod):
        rho = sod['rho']
        N = len(rho)
        dx = 1.0 / N
        mass = np.sum(rho) * dx
        expected = 0.5 * 1.0 + 0.5 * 0.125  # 0.5625
        assert abs(mass - expected) / expected < 1e-5, \
            f"Mass = {mass}, expected {expected}"

    def test_momentum_balance(self, sod):
        rho = sod['rho']
        u = sod['u']
        N = len(rho)
        dx = 1.0 / N
        momentum = np.sum(rho * u) * dx
        expected = 0.225
        assert abs(momentum - expected) < 0.002, \
            f"Momentum = {momentum}, expected ~{expected}"

    def test_energy_conservation(self, sod):
        rho = sod['rho']
        u = sod['u']
        p = sod['p']
        N = len(rho)
        dx = 1.0 / N
        E = p / 0.4 + 0.5 * rho * u ** 2
        energy = np.sum(E) * dx
        expected = 0.5 * (1.0 / 0.4) + 0.5 * (0.1 / 0.4)  # 1.375
        assert abs(energy - expected) / expected < 1e-4, \
            f"Energy = {energy}, expected {expected}"


# -- Einfeldt problem: positivity and symmetry --------------------------------

class TestEinfeldtPhysics:
    @pytest.fixture
    def einfeldt(self):
        return np.genfromtxt('/app/results/einfeldt.csv', delimiter=',',
                             names=True)

    def test_density_positive(self, einfeldt):
        assert np.all(einfeldt['rho'] > 0), \
            f"Negative density; min = {np.min(einfeldt['rho'])}"

    def test_pressure_positive(self, einfeldt):
        assert np.all(einfeldt['p'] > 0), \
            f"Negative pressure; min = {np.min(einfeldt['p'])}"

    def test_density_symmetry(self, einfeldt):
        rho = einfeldt['rho']
        rho_rev = rho[::-1]
        err = np.mean(np.abs(rho - rho_rev))
        assert err < 0.01, f"Symmetry error = {err}"


# -- Blast problem: positivity and conservation --------------------------------

class TestBlastPhysics:
    @pytest.fixture
    def blast(self):
        return np.genfromtxt('/app/results/blast.csv', delimiter=',',
                             names=True)

    def test_density_positive(self, blast):
        assert np.all(blast['rho'] > 0), \
            f"Negative density; min = {np.min(blast['rho'])}"

    def test_pressure_positive(self, blast):
        assert np.all(blast['p'] > 0), \
            f"Negative pressure; min = {np.min(blast['p'])}"

    def test_mass_conservation(self, blast):
        rho = blast['rho']
        N = len(rho)
        dx = 1.0 / N
        mass = np.sum(rho) * dx
        expected = 1.0
        assert abs(mass - expected) / expected < 1e-4, \
            f"Mass = {mass}, expected {expected}"


# -- Convergence study results ------------------------------------------------

class TestConvergenceStudy:
    @pytest.fixture
    def conv(self):
        with open('/app/results/convergence.json') as f:
            return json.load(f)

    def test_convergence_json_exists(self):
        assert os.path.exists('/app/results/convergence.json'), \
            "convergence.json not found"

    def test_has_required_fields(self, conv):
        for field in ['convergence_rate', 'l1_errors', 'resolutions', 'pass']:
            assert field in conv, f"Missing field: {field}"

    def test_four_resolutions(self, conv):
        assert len(conv['resolutions']) == 4
        assert conv['resolutions'] == [100, 200, 400, 800]

    def test_convergence_rate_sufficient(self, conv):
        rate = conv['convergence_rate']
        assert rate >= 0.7, \
            f"Convergence rate {rate} < 0.7"

    def test_convergence_rate_reasonable(self, conv):
        rate = conv['convergence_rate']
        assert rate <= 2.5, \
            f"Convergence rate {rate} > 2.5"

    def test_errors_decrease_monotonically(self, conv):
        errors = conv['l1_errors']
        for i in range(len(errors) - 1):
            assert errors[i] > errors[i + 1], \
                f"Error did not decrease: N={conv['resolutions'][i]} " \
                f"err={errors[i]} -> N={conv['resolutions'][i+1]} " \
                f"err={errors[i+1]}"

    def test_finest_error_small(self, conv):
        assert conv['l1_errors'][-1] < 0.01, \
            f"Finest mesh error {conv['l1_errors'][-1]} >= 0.01"

    def test_coarsest_error_reasonable(self, conv):
        assert conv['l1_errors'][0] < 0.1, \
            f"Coarsest mesh error {conv['l1_errors'][0]} >= 0.1"
        assert conv['l1_errors'][0] > 1e-5, \
            f"Coarsest mesh error {conv['l1_errors'][0]} suspiciously small"

    def test_study_passes(self, conv):
        assert conv['pass'] is True, "Convergence study did not pass"


# -- Convergence plot ---------------------------------------------------------

class TestConvergencePlot:
    def test_plot_exists(self):
        assert os.path.exists('/app/results/convergence.png'), \
            "Convergence plot not found"

    def test_plot_size(self):
        size = os.path.getsize('/app/results/convergence.png')
        assert size > 1000, \
            f"Plot file too small ({size} bytes), likely empty or corrupt"

    def test_plot_is_valid_png(self):
        with open('/app/results/convergence.png', 'rb') as f:
            header = f.read(8)
        assert header[:4] == b'\x89PNG', "File is not a valid PNG"


# -- SQLite results database --------------------------------------------------

class TestResultsDatabase:
    @pytest.fixture
    def db(self):
        conn = sqlite3.connect('/app/results/results.db')
        yield conn
        conn.close()

    def test_db_exists(self):
        assert os.path.exists('/app/results/results.db'), \
            "Results database not found"

    def test_sod_table_exists(self, db):
        cursor = db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='sod'"
        )
        assert cursor.fetchone() is not None, "Table 'sod' not found"

    def test_sod_column_names(self, db):
        cursor = db.execute("PRAGMA table_info(sod)")
        cols = [row[1] for row in cursor.fetchall()]
        for expected in ['x', 'rho', 'u', 'p']:
            assert expected in cols, \
                f"Column '{expected}' not in sod table (found: {cols})"

    def test_sod_row_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM sod").fetchone()[0]
        assert count >= 100, f"sod table has {count} rows, expected >= 100"

    def test_sod_density_range_sql(self, db):
        row = db.execute("SELECT MIN(rho), MAX(rho) FROM sod").fetchone()
        assert row[0] > 0, f"Negative density in sod: min={row[0]}"
        assert row[1] < 2.0, f"Unreasonable max density: {row[1]}"

    def test_einfeldt_row_count(self, db):
        count = db.execute(
            "SELECT COUNT(*) FROM einfeldt"
        ).fetchone()[0]
        assert count >= 100, \
            f"einfeldt table has {count} rows, expected >= 100"

    def test_blast_row_count(self, db):
        count = db.execute(
            "SELECT COUNT(*) FROM blast"
        ).fetchone()[0]
        assert count >= 100, \
            f"blast table has {count} rows, expected >= 100"

    def test_convergence_table_schema(self, db):
        cursor = db.execute("PRAGMA table_info(convergence)")
        cols = [row[1] for row in cursor.fetchall()]
        for expected in ['ncells', 'dx', 'l1_error']:
            assert expected in cols, \
                f"Column '{expected}' not in convergence table (found: {cols})"

    def test_convergence_row_count(self, db):
        rows = db.execute(
            "SELECT ncells, dx, l1_error FROM convergence ORDER BY ncells"
        ).fetchall()
        assert len(rows) == 4, \
            f"convergence table has {len(rows)} rows, expected 4"
        ncells_vals = [r[0] for r in rows]
        assert ncells_vals == [100, 200, 400, 800], \
            f"Unexpected resolutions: {ncells_vals}"

    def test_convergence_errors_decrease_in_db(self, db):
        rows = db.execute(
            "SELECT l1_error FROM convergence ORDER BY ncells"
        ).fetchall()
        errors = [r[0] for r in rows]
        for i in range(len(errors) - 1):
            assert errors[i] > errors[i + 1], \
                f"Errors not monotonically decreasing in DB: {errors}"


# -- Makefile pipeline integration --------------------------------------------

class TestPipeline:
    def test_make_validate_succeeds(self):
        """Verify the Makefile pipeline runs end-to-end."""
        import subprocess
        result = subprocess.run(
            ['make', '-C', '/app', 'validate'],
            capture_output=True, text=True,
            timeout=180
        )
        assert result.returncode == 0, \
            f"make validate failed (rc={result.returncode}):\n" \
            f"{result.stderr[:1000]}"
