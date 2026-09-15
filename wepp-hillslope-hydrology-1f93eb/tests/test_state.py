"""
Tests for the WEPP Surface Hydrology Pipeline.

Verifies Fortran library compilation, ctypes FFI, CLIGEN PAR file parsing,
SQLite database schema, hydrology simulation accuracy, gnuplot output,
and report query outputs.

"""

import ctypes
import json
import math
import os
import subprocess
import sqlite3
import pytest

TOOL_PATH = "/app/wepp_pipeline.py"
DB_PATH = "/app/results.db"
STATIONS_DIR = "/app/stations"
SCENARIOS_DIR = "/app/scenarios"

SCENARIOS = ["constant_rain", "no_ponding", "variable_rain", "short_intense", "multi_burst"]

GOLDEN = {
    "constant_rain": {
        "ponding_time_min": 12.0,
        "cumulative_infiltration_mm": 19.64,
        "total_rainfall_mm": 30.0,
        "rainfall_excess_mm": 10.36,
        "depression_storage_mm": 2.4,
        "net_runoff_mm": 7.96,
        "peak_discharge_mm_hr": 17.22,
    },
    "no_ponding": {
        "ponding_time_min": -1.0,
        "cumulative_infiltration_mm": 10.0,
        "total_rainfall_mm": 10.0,
        "rainfall_excess_mm": 0.0,
        "net_runoff_mm": 0.0,
        "peak_discharge_mm_hr": 0.0,
    },
    "variable_rain": {
        "ponding_time_min": 20.56,
        "cumulative_infiltration_mm": 15.76,
        "total_rainfall_mm": 22.33,
        "rainfall_excess_mm": 6.58,
        "depression_storage_mm": 2.4,
        "net_runoff_mm": 4.18,
        "peak_discharge_mm_hr": 26.22,
    },
    "short_intense": {
        "ponding_time_min": 1.53,
        "cumulative_infiltration_mm": 7.28,
        "total_rainfall_mm": 13.33,
        "rainfall_excess_mm": 6.06,
        "depression_storage_mm": 4.656,
        "net_runoff_mm": 1.40,
        "peak_discharge_mm_hr": 49.11,
    },
    "multi_burst": {
        "ponding_time_min": 15.0,
        "cumulative_infiltration_mm": 16.47,
        "total_rainfall_mm": 24.58,
        "rainfall_excess_mm": 8.12,
        "depression_storage_mm": 8.115,
    },
}


def approx_eq(a, b, rel_tol=0.03, abs_tol=0.1):
    if abs(b) < 1e-6:
        return abs(a) < abs_tol
    return abs(a - b) / max(abs(b), 1e-12) < rel_tol or abs(a - b) < abs_tol


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def run_cmd(args, timeout=60):
    result = subprocess.run(
        ["python3", TOOL_PATH] + args,
        capture_output=True, text=True, timeout=timeout
    )
    return result


@pytest.fixture(scope="session", autouse=True)
def pipeline_setup():
    """Compile Fortran library, then run ingest, simulate, and plot."""
    # Verify build system
    assert os.path.isfile("/app/Makefile"), "Makefile not found at /app/Makefile"
    make_result = subprocess.run(
        ["make", "-C", "/app"], capture_output=True, text=True, timeout=60
    )
    assert make_result.returncode == 0, (
        f"make failed:\nstdout: {make_result.stdout}\nstderr: {make_result.stderr}"
    )
    assert os.path.isfile("/app/libgaml.so"), "libgaml.so not built by make"

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    assert os.path.isfile(TOOL_PATH), f"Pipeline tool not found at {TOOL_PATH}"

    # Ingest the Lafayette PAR file
    par_file = os.path.join(STATIONS_DIR, "lafayette.par")
    assert os.path.isfile(par_file), f"PAR file not found: {par_file}"
    result = run_cmd(["ingest", par_file], timeout=30)
    assert result.returncode == 0, (
        f"Ingest failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )

    # Simulate all scenarios
    for name in SCENARIOS:
        scenario_file = os.path.join(SCENARIOS_DIR, f"{name}.json")
        assert os.path.isfile(scenario_file), f"Scenario not found: {scenario_file}"
        result = run_cmd(["simulate", scenario_file], timeout=60)
        assert result.returncode == 0, (
            f"Simulate {name} failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    # Plot all scenarios
    for name in SCENARIOS:
        scenario_file = os.path.join(SCENARIOS_DIR, f"{name}.json")
        result = run_cmd(["plot", scenario_file], timeout=60)
        assert result.returncode == 0, (
            f"Plot {name} failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ==================== FORTRAN LIBRARY ====================

class TestFortranLibrary:
    """Tests that the compiled Fortran library works correctly via ctypes."""

    def test_libgaml_exists(self):
        assert os.path.isfile("/app/libgaml.so"), "libgaml.so not found"

    def test_makefile_exists(self):
        assert os.path.isfile("/app/Makefile"), "Makefile not found"

    def test_makefile_references_fortran(self):
        content = open("/app/Makefile").read()
        assert "gaml_core" in content, "Makefile does not reference gaml_core"
        assert "clean" in content, "Makefile missing clean target"

    def test_gaml_g_func_basic(self):
        """G(10, 30) = 10 - 30*ln(1+10/30)"""
        lib = ctypes.CDLL("/app/libgaml.so")
        F = ctypes.c_double(10.0)
        Ns_td = ctypes.c_double(30.0)
        result = ctypes.c_double()
        lib.gaml_g_func(ctypes.byref(F), ctypes.byref(Ns_td), ctypes.byref(result))
        expected = 10.0 - 30.0 * math.log(1.0 + 10.0 / 30.0)
        assert abs(result.value - expected) < 1e-6, (
            f"gaml_g_func(10,30) = {result.value}, expected {expected}"
        )

    def test_gaml_g_func_zero(self):
        """G(0, x) = 0"""
        lib = ctypes.CDLL("/app/libgaml.so")
        F = ctypes.c_double(0.0)
        Ns_td = ctypes.c_double(30.0)
        result = ctypes.c_double()
        lib.gaml_g_func(ctypes.byref(F), ctypes.byref(Ns_td), ctypes.byref(result))
        assert abs(result.value) < 1e-10, f"G(0) should be 0, got {result.value}"

    def test_gaml_g_func_large(self):
        """G(50, 30) = 50 - 30*ln(1+50/30)"""
        lib = ctypes.CDLL("/app/libgaml.so")
        F = ctypes.c_double(50.0)
        Ns_td = ctypes.c_double(30.0)
        result = ctypes.c_double()
        lib.gaml_g_func(ctypes.byref(F), ctypes.byref(Ns_td), ctypes.byref(result))
        expected = 50.0 - 30.0 * math.log(1.0 + 50.0 / 30.0)
        assert abs(result.value - expected) < 1e-6

    def test_gaml_solve_f_roundtrip(self):
        """Solve G(F)=G(15) should recover F=15"""
        lib = ctypes.CDLL("/app/libgaml.so")
        # First compute G(15, 30)
        F_orig = ctypes.c_double(15.0)
        Ns_td = ctypes.c_double(30.0)
        g_val = ctypes.c_double()
        lib.gaml_g_func(ctypes.byref(F_orig), ctypes.byref(Ns_td), ctypes.byref(g_val))
        # Now solve for F
        F_guess = ctypes.c_double(20.0)
        tol = ctypes.c_double(1e-10)
        max_iter = ctypes.c_int(200)
        F_result = ctypes.c_double()
        lib.gaml_solve_f(
            ctypes.byref(g_val), ctypes.byref(Ns_td),
            ctypes.byref(F_guess), ctypes.byref(tol),
            ctypes.byref(max_iter), ctypes.byref(F_result)
        )
        assert abs(F_result.value - 15.0) < 0.001, (
            f"Roundtrip: expected 15.0, got {F_result.value}"
        )

    def test_gaml_solve_f_different_ns(self):
        """Solve G(F)=G(25) with Ns_td=50 should recover F=25"""
        lib = ctypes.CDLL("/app/libgaml.so")
        F_orig = ctypes.c_double(25.0)
        Ns_td = ctypes.c_double(50.0)
        g_val = ctypes.c_double()
        lib.gaml_g_func(ctypes.byref(F_orig), ctypes.byref(Ns_td), ctypes.byref(g_val))
        F_guess = ctypes.c_double(10.0)
        tol = ctypes.c_double(1e-10)
        max_iter = ctypes.c_int(200)
        F_result = ctypes.c_double()
        lib.gaml_solve_f(
            ctypes.byref(g_val), ctypes.byref(Ns_td),
            ctypes.byref(F_guess), ctypes.byref(tol),
            ctypes.byref(max_iter), ctypes.byref(F_result)
        )
        assert abs(F_result.value - 25.0) < 0.001, (
            f"Expected 25.0, got {F_result.value}"
        )

    def test_gaml_infil_rate_basic(self):
        """f(5, 30, 10) = 5 * (1 + 30/10) = 20"""
        lib = ctypes.CDLL("/app/libgaml.so")
        Ke = ctypes.c_double(5.0)
        Ns_td = ctypes.c_double(30.0)
        F_cum = ctypes.c_double(10.0)
        rate = ctypes.c_double()
        lib.gaml_infil_rate(
            ctypes.byref(Ke), ctypes.byref(Ns_td),
            ctypes.byref(F_cum), ctypes.byref(rate)
        )
        assert abs(rate.value - 20.0) < 0.01, (
            f"Infil rate: expected 20.0, got {rate.value}"
        )

    def test_gaml_infil_rate_high_f(self):
        """f(5, 30, 100) = 5 * (1 + 30/100) = 6.5"""
        lib = ctypes.CDLL("/app/libgaml.so")
        Ke = ctypes.c_double(5.0)
        Ns_td = ctypes.c_double(30.0)
        F_cum = ctypes.c_double(100.0)
        rate = ctypes.c_double()
        lib.gaml_infil_rate(
            ctypes.byref(Ke), ctypes.byref(Ns_td),
            ctypes.byref(F_cum), ctypes.byref(rate)
        )
        assert abs(rate.value - 6.5) < 0.01, (
            f"Infil rate: expected 6.5, got {rate.value}"
        )


# ==================== GNUPLOT OUTPUT ====================

class TestGnuplotOutput:
    """Tests that gnuplot-generated hydrograph plots exist and are valid."""

    def test_plots_directory_exists(self):
        assert os.path.isdir("/app/plots"), "/app/plots directory not found"

    def test_constant_rain_plot_exists(self):
        path = "/app/plots/constant_rain.png"
        assert os.path.isfile(path), f"Plot not found: {path}"
        assert os.path.getsize(path) > 1024, (
            f"Plot too small: {os.path.getsize(path)} bytes"
        )

    def test_variable_rain_plot_exists(self):
        path = "/app/plots/variable_rain.png"
        assert os.path.isfile(path), f"Plot not found: {path}"
        assert os.path.getsize(path) > 1024

    def test_short_intense_plot_exists(self):
        path = "/app/plots/short_intense.png"
        assert os.path.isfile(path), f"Plot not found: {path}"
        assert os.path.getsize(path) > 1024

    def test_no_ponding_plot_exists(self):
        path = "/app/plots/no_ponding.png"
        assert os.path.isfile(path), f"Plot not found: {path}"
        assert os.path.getsize(path) > 1024

    def test_multi_burst_plot_exists(self):
        path = "/app/plots/multi_burst.png"
        assert os.path.isfile(path), f"Plot not found: {path}"
        assert os.path.getsize(path) > 1024

    def test_plot_is_valid_png(self):
        """Verify at least one file has a PNG header."""
        path = "/app/plots/constant_rain.png"
        with open(path, "rb") as f:
            header = f.read(8)
        assert header[:4] == b'\x89PNG', "File does not have PNG header"


# ==================== DATABASE SCHEMA ====================

class TestDatabaseSchema:

    def test_database_exists(self):
        assert os.path.isfile(DB_PATH), "Database file not created"

    def test_stations_table_exists(self):
        conn = get_db()
        row = conn.execute(
            "SELECT count(*) as c FROM sqlite_master "
            "WHERE type='table' AND name='stations'"
        ).fetchone()
        assert row["c"] == 1, "stations table not found"
        conn.close()

    def test_monthly_precip_table_exists(self):
        conn = get_db()
        row = conn.execute(
            "SELECT count(*) as c FROM sqlite_master "
            "WHERE type='table' AND name='monthly_precip'"
        ).fetchone()
        assert row["c"] == 1, "monthly_precip table not found"
        conn.close()

    def test_simulations_table_exists(self):
        conn = get_db()
        row = conn.execute(
            "SELECT count(*) as c FROM sqlite_master "
            "WHERE type='table' AND name='simulations'"
        ).fetchone()
        assert row["c"] == 1, "simulations table not found"
        conn.close()

    def test_stations_has_data(self):
        conn = get_db()
        row = conn.execute("SELECT count(*) as c FROM stations").fetchone()
        assert row["c"] >= 1, "No stations in database"
        conn.close()

    def test_monthly_precip_has_12_months(self):
        conn = get_db()
        row = conn.execute(
            "SELECT count(*) as c FROM monthly_precip"
        ).fetchone()
        assert row["c"] >= 12, f"Expected >= 12 monthly records, got {row['c']}"
        conn.close()

    def test_simulations_count(self):
        conn = get_db()
        row = conn.execute("SELECT count(*) as c FROM simulations").fetchone()
        assert row["c"] >= 5, f"Expected >= 5 simulations, got {row['c']}"
        conn.close()


# ==================== PAR FILE PARSING ====================

class TestPARParsing:

    def _query_station(self, field):
        conn = get_db()
        row = conn.execute(
            f"SELECT {field} FROM stations WHERE name LIKE '%LAFAYETTE%'"
        ).fetchone()
        conn.close()
        assert row is not None, "Lafayette station not found"
        return row[0]

    def _query_precip(self, month, field):
        conn = get_db()
        row = conn.execute(
            f"SELECT {field} FROM monthly_precip mp "
            "JOIN stations s ON mp.station_id = s.id "
            "WHERE s.name LIKE '%LAFAYETTE%' AND mp.month = ?",
            (month,)
        ).fetchone()
        conn.close()
        assert row is not None, f"No data for month {month}"
        return row[0]

    def test_station_name(self):
        conn = get_db()
        row = conn.execute("SELECT name FROM stations").fetchone()
        conn.close()
        name = row["name"].strip()
        assert "LAFAYETTE" in name, f"Expected LAFAYETTE in name, got '{name}'"

    def test_latitude(self):
        val = self._query_station("latitude")
        assert abs(val - 40.35) < 0.01, f"latitude: expected 40.35, got {val}"

    def test_longitude(self):
        val = self._query_station("longitude")
        assert abs(val - (-86.87)) < 0.01, f"longitude: expected -86.87, got {val}"

    def test_elevation(self):
        val = self._query_station("elevation_ft")
        assert abs(val - 600.0) < 1.0, f"elevation: expected 600, got {val}"

    def test_years(self):
        val = self._query_station("years")
        assert val == 40, f"years: expected 40, got {val}"

    def test_mean_precip_january(self):
        val = self._query_precip(1, "mean_in")
        assert abs(val - 0.22) < 0.01, f"Jan mean_in: expected 0.22, got {val}"

    def test_mean_precip_june(self):
        val = self._query_precip(6, "mean_in")
        assert abs(val - 0.42) < 0.01, f"Jun mean_in: expected 0.42, got {val}"

    def test_mean_precip_august(self):
        val = self._query_precip(8, "mean_in")
        assert abs(val - 0.45) < 0.01, f"Aug mean_in: expected 0.45, got {val}"

    def test_sd_precip_june(self):
        val = self._query_precip(6, "sd_in")
        assert abs(val - 0.55) < 0.01, f"Jun sd_in: expected 0.55, got {val}"

    def test_skew_precip_march(self):
        val = self._query_precip(3, "skew")
        assert abs(val - 3.05) < 0.02, f"Mar skew: expected 3.05, got {val}"

    def test_prob_ww_may(self):
        val = self._query_precip(5, "prob_ww")
        assert abs(val - 0.50) < 0.01, f"May P(W/W): expected 0.50, got {val}"

    def test_prob_wd_march(self):
        val = self._query_precip(3, "prob_wd")
        assert abs(val - 0.29) < 0.01, f"Mar P(W/D): expected 0.29, got {val}"

    def test_max_30min_june(self):
        val = self._query_precip(6, "max_30min_in_hr")
        assert abs(val - 1.37) < 0.01, f"Jun MX.5P: expected 1.37, got {val}"

    def test_max_30min_december(self):
        val = self._query_precip(12, "max_30min_in_hr")
        assert abs(val - 0.37) < 0.01, f"Dec MX.5P: expected 0.37, got {val}"

    def test_all_12_months_present(self):
        conn = get_db()
        rows = conn.execute(
            "SELECT DISTINCT mp.month FROM monthly_precip mp "
            "JOIN stations s ON mp.station_id = s.id "
            "WHERE s.name LIKE '%LAFAYETTE%' ORDER BY mp.month"
        ).fetchall()
        conn.close()
        months = [r["month"] for r in rows]
        assert months == list(range(1, 13)), f"Missing months: got {months}"


# ==================== MASS BALANCE ====================

class TestMassBalance:

    def _get_sim(self, scenario):
        conn = get_db()
        row = conn.execute(
            "SELECT * FROM simulations WHERE scenario = ?", (scenario,)
        ).fetchone()
        conn.close()
        assert row is not None, f"Scenario '{scenario}' not found"
        return dict(row)

    def test_constant_rain(self):
        r = self._get_sim("constant_rain")
        total = r["cumulative_infiltration_mm"] + r["rainfall_excess_mm"]
        assert abs(total - r["total_rainfall_mm"]) / r["total_rainfall_mm"] < 0.01

    def test_variable_rain(self):
        r = self._get_sim("variable_rain")
        total = r["cumulative_infiltration_mm"] + r["rainfall_excess_mm"]
        assert abs(total - r["total_rainfall_mm"]) / r["total_rainfall_mm"] < 0.01

    def test_short_intense(self):
        r = self._get_sim("short_intense")
        total = r["cumulative_infiltration_mm"] + r["rainfall_excess_mm"]
        assert abs(total - r["total_rainfall_mm"]) / r["total_rainfall_mm"] < 0.01

    def test_multi_burst(self):
        r = self._get_sim("multi_burst")
        total = r["cumulative_infiltration_mm"] + r["rainfall_excess_mm"]
        assert abs(total - r["total_rainfall_mm"]) / r["total_rainfall_mm"] < 0.01

    def test_no_ponding(self):
        r = self._get_sim("no_ponding")
        total = r["cumulative_infiltration_mm"] + r["rainfall_excess_mm"]
        assert abs(total - r["total_rainfall_mm"]) / max(r["total_rainfall_mm"], 0.01) < 0.01


# ==================== PHYSICAL CONSTRAINTS ====================

class TestPhysicalConstraints:

    def _get_all_sims(self):
        conn = get_db()
        rows = conn.execute("SELECT * FROM simulations").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def test_infiltration_non_negative(self):
        for r in self._get_all_sims():
            assert r["cumulative_infiltration_mm"] >= 0, (
                f"{r['scenario']}: negative infiltration"
            )

    def test_infiltration_le_rainfall(self):
        for r in self._get_all_sims():
            assert r["cumulative_infiltration_mm"] <= r["total_rainfall_mm"] + 0.1, (
                f"{r['scenario']}: infiltration exceeds rainfall"
            )

    def test_excess_non_negative(self):
        for r in self._get_all_sims():
            assert r["rainfall_excess_mm"] >= -0.01, (
                f"{r['scenario']}: negative excess"
            )

    def test_net_runoff_le_excess(self):
        for r in self._get_all_sims():
            assert r["net_runoff_mm"] <= r["rainfall_excess_mm"] + 0.1, (
                f"{r['scenario']}: runoff exceeds excess"
            )

    def test_depression_storage_non_negative(self):
        for r in self._get_all_sims():
            assert r["depression_storage_mm"] >= 0, (
                f"{r['scenario']}: negative depression storage"
            )

    def test_peak_positive_when_runoff(self):
        for r in self._get_all_sims():
            if r["net_runoff_mm"] > 0.1:
                assert r["peak_discharge_mm_hr"] > 0, (
                    f"{r['scenario']}: zero peak with nonzero runoff"
                )

    def test_no_runoff_when_no_ponding(self):
        conn = get_db()
        r = dict(conn.execute(
            "SELECT * FROM simulations WHERE scenario = 'no_ponding'"
        ).fetchone())
        conn.close()
        assert r["rainfall_excess_mm"] < 0.01
        assert r["net_runoff_mm"] < 0.01
        assert r["peak_discharge_mm_hr"] < 0.01


# ==================== NUMERICAL ACCURACY ====================

class TestNumericalAccuracy:

    def _get_sim(self, scenario):
        conn = get_db()
        row = conn.execute(
            "SELECT * FROM simulations WHERE scenario = ?", (scenario,)
        ).fetchone()
        conn.close()
        assert row is not None
        return dict(row)

    # --- Constant rain ---

    def test_constant_rain_ponding_time(self):
        r = self._get_sim("constant_rain")
        assert approx_eq(r["ponding_time_min"], 12.0, rel_tol=0.03)

    def test_constant_rain_infiltration(self):
        r = self._get_sim("constant_rain")
        assert approx_eq(r["cumulative_infiltration_mm"], 19.64, rel_tol=0.03)

    def test_constant_rain_excess(self):
        r = self._get_sim("constant_rain")
        assert approx_eq(r["rainfall_excess_mm"], 10.36, rel_tol=0.03)

    def test_constant_rain_depression(self):
        r = self._get_sim("constant_rain")
        assert approx_eq(r["depression_storage_mm"], 2.4, rel_tol=0.02)

    def test_constant_rain_net_runoff(self):
        r = self._get_sim("constant_rain")
        assert approx_eq(r["net_runoff_mm"], 7.96, rel_tol=0.05)

    def test_constant_rain_peak(self):
        r = self._get_sim("constant_rain")
        assert approx_eq(r["peak_discharge_mm_hr"], 17.22, rel_tol=0.08)

    # --- No ponding ---

    def test_no_ponding_ponding_time(self):
        r = self._get_sim("no_ponding")
        assert r["ponding_time_min"] < 0

    def test_no_ponding_infiltration(self):
        r = self._get_sim("no_ponding")
        assert approx_eq(r["cumulative_infiltration_mm"], 10.0, rel_tol=0.01)

    # --- Variable rain ---

    def test_variable_rain_ponding_time(self):
        r = self._get_sim("variable_rain")
        assert approx_eq(r["ponding_time_min"], 20.56, rel_tol=0.05)

    def test_variable_rain_infiltration(self):
        r = self._get_sim("variable_rain")
        assert approx_eq(r["cumulative_infiltration_mm"], 15.76, rel_tol=0.03)

    def test_variable_rain_excess(self):
        r = self._get_sim("variable_rain")
        assert approx_eq(r["rainfall_excess_mm"], 6.58, rel_tol=0.05)

    def test_variable_rain_net_runoff(self):
        r = self._get_sim("variable_rain")
        assert approx_eq(r["net_runoff_mm"], 4.18, rel_tol=0.05)

    def test_variable_rain_peak(self):
        r = self._get_sim("variable_rain")
        assert approx_eq(r["peak_discharge_mm_hr"], 26.22, rel_tol=0.10)

    # --- Short intense ---

    def test_short_intense_ponding_time(self):
        r = self._get_sim("short_intense")
        assert approx_eq(r["ponding_time_min"], 1.53, rel_tol=0.05)

    def test_short_intense_infiltration(self):
        r = self._get_sim("short_intense")
        assert approx_eq(r["cumulative_infiltration_mm"], 7.28, rel_tol=0.03)

    def test_short_intense_excess(self):
        r = self._get_sim("short_intense")
        assert approx_eq(r["rainfall_excess_mm"], 6.06, rel_tol=0.05)

    def test_short_intense_peak(self):
        r = self._get_sim("short_intense")
        assert approx_eq(r["peak_discharge_mm_hr"], 49.11, rel_tol=0.10)

    # --- Multi burst ---

    def test_multi_burst_ponding_time(self):
        r = self._get_sim("multi_burst")
        assert approx_eq(r["ponding_time_min"], 15.0, rel_tol=0.05)

    def test_multi_burst_infiltration(self):
        r = self._get_sim("multi_burst")
        assert approx_eq(r["cumulative_infiltration_mm"], 16.47, rel_tol=0.03)

    def test_multi_burst_depression(self):
        r = self._get_sim("multi_burst")
        assert approx_eq(r["depression_storage_mm"], 8.115, rel_tol=0.02)

    def test_multi_burst_near_zero_runoff(self):
        r = self._get_sim("multi_burst")
        assert r["net_runoff_mm"] < 0.5


# ==================== GAML BEHAVIOR ====================

class TestGAMLBehavior:

    def _get_sim(self, scenario):
        conn = get_db()
        row = conn.execute(
            "SELECT * FROM simulations WHERE scenario = ?", (scenario,)
        ).fetchone()
        conn.close()
        return dict(row)

    def test_ponding_during_storm(self):
        r = self._get_sim("constant_rain")
        assert 0 < r["ponding_time_min"] < 60

    def test_ponding_analytical(self):
        """For constant rain, ponding time should match the analytical solution."""
        r = self._get_sim("constant_rain")
        Ke, Ns, td, rain = 5.0, 100.0, 0.3, 30.0
        F_p = Ke * Ns * td / (rain - Ke)
        tp_analytical = F_p / rain * 60.0
        assert abs(r["ponding_time_min"] - tp_analytical) / tp_analytical < 0.02

    def test_variable_rain_ponding_in_burst(self):
        """Ponding should begin during the high-intensity period, not during low."""
        r = self._get_sim("variable_rain")
        assert 20.0 <= r["ponding_time_min"] < 25.0

    def test_short_intense_early_ponding(self):
        """High intensity with low Ke should cause very fast ponding."""
        r = self._get_sim("short_intense")
        assert 0 < r["ponding_time_min"] < 3.0

    def test_peak_bounded_by_rainfall(self):
        r = self._get_sim("constant_rain")
        assert r["peak_discharge_mm_hr"] > 10.0
        assert r["peak_discharge_mm_hr"] < 35.0


# ==================== DEPRESSION STORAGE ====================

class TestDepressionStorage:

    def _get_sim(self, scenario):
        conn = get_db()
        row = conn.execute(
            "SELECT * FROM simulations WHERE scenario = ?", (scenario,)
        ).fetchone()
        conn.close()
        return dict(row)

    def test_constant_rain_formula(self):
        r = self._get_sim("constant_rain")
        # rr=8, slope=5%
        expected = 0.112 * 8 + 0.031 * 64 - 0.012 * 8 * 5
        assert abs(r["depression_storage_mm"] - expected) / expected < 0.01

    def test_short_intense_formula(self):
        r = self._get_sim("short_intense")
        # rr=12, slope=8%
        expected = 0.112 * 12 + 0.031 * 144 - 0.012 * 12 * 8
        assert abs(r["depression_storage_mm"] - expected) / expected < 0.01

    def test_multi_burst_formula(self):
        r = self._get_sim("multi_burst")
        # rr=15, slope=3%
        expected = 0.112 * 15 + 0.031 * 225 - 0.012 * 15 * 3
        assert abs(r["depression_storage_mm"] - expected) / expected < 0.01


# ==================== VOLUME CONTINUITY ====================

class TestVolumeContinuity:

    def _get_sim(self, scenario):
        conn = get_db()
        row = conn.execute(
            "SELECT * FROM simulations WHERE scenario = ?", (scenario,)
        ).fetchone()
        conn.close()
        return dict(row)

    def test_constant_rain(self):
        r = self._get_sim("constant_rain")
        if r["peak_discharge_mm_hr"] > 0 and r["effective_duration_hr"] > 0:
            V = r["peak_discharge_mm_hr"] * r["effective_duration_hr"]
            assert abs(V - r["net_runoff_mm"]) / r["net_runoff_mm"] < 0.05

    def test_variable_rain(self):
        r = self._get_sim("variable_rain")
        if r["peak_discharge_mm_hr"] > 0 and r["effective_duration_hr"] > 0:
            V = r["peak_discharge_mm_hr"] * r["effective_duration_hr"]
            assert abs(V - r["net_runoff_mm"]) / r["net_runoff_mm"] < 0.05

    def test_short_intense(self):
        r = self._get_sim("short_intense")
        if r["peak_discharge_mm_hr"] > 0 and r["effective_duration_hr"] > 0:
            V = r["peak_discharge_mm_hr"] * r["effective_duration_hr"]
            assert abs(V - r["net_runoff_mm"]) / r["net_runoff_mm"] < 0.05


# ==================== REPORT OUTPUTS ====================

class TestReports:

    def _run_report(self, query_name):
        result = run_cmd(["report", query_name], timeout=30)
        assert result.returncode == 0, (
            f"Report '{query_name}' failed:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        data = json.loads(result.stdout)
        assert isinstance(data, list), f"Expected JSON array, got {type(data)}"
        return data

    # --- wettest-months ---

    def test_wettest_months_structure(self):
        data = self._run_report("wettest-months")
        assert len(data) >= 3
        for item in data:
            assert "station" in item, f"Missing 'station' key: {item}"
            assert "month" in item, f"Missing 'month' key: {item}"
            assert "mean_in" in item, f"Missing 'mean_in' key: {item}"

    def test_wettest_months_ordering(self):
        data = self._run_report("wettest-months")
        means = [item["mean_in"] for item in data[:3]]
        assert means == sorted(means, reverse=True), (
            f"Top 3 not sorted descending: {means}"
        )

    def test_wettest_months_top3_values(self):
        data = self._run_report("wettest-months")
        # Lafayette: Aug(0.45), Jun(0.42), Jul(0.41)
        assert data[0]["month"] == 8, f"Expected month 8 first, got {data[0]['month']}"
        assert abs(data[0]["mean_in"] - 0.45) < 0.01
        assert data[1]["month"] == 6, f"Expected month 6 second, got {data[1]['month']}"
        assert abs(data[1]["mean_in"] - 0.42) < 0.01
        assert data[2]["month"] == 7, f"Expected month 7 third, got {data[2]['month']}"
        assert abs(data[2]["mean_in"] - 0.41) < 0.01

    # --- runoff-ranking ---

    def test_runoff_ranking_structure(self):
        data = self._run_report("runoff-ranking")
        assert len(data) >= 5
        for item in data:
            assert "scenario" in item, f"Missing 'scenario' key: {item}"
            assert "net_runoff_mm" in item, f"Missing 'net_runoff_mm' key: {item}"
            assert "peak_discharge_mm_hr" in item, f"Missing 'peak_discharge_mm_hr': {item}"

    def test_runoff_ranking_ordering(self):
        data = self._run_report("runoff-ranking")
        runoffs = [item["net_runoff_mm"] for item in data]
        assert runoffs == sorted(runoffs, reverse=True), (
            f"Not sorted descending: {runoffs}"
        )

    def test_runoff_ranking_top(self):
        data = self._run_report("runoff-ranking")
        assert data[0]["scenario"] == "constant_rain", (
            f"Expected constant_rain first, got {data[0]['scenario']}"
        )
        assert abs(data[0]["net_runoff_mm"] - 7.96) < 0.5
