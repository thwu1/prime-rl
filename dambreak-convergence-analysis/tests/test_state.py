"""
Tests for the granular dam break analysis tool.
Verifies analytical solution accuracy, ESRI ASCII format, GeoTIFF output,
SQLite database, mass conservation, convergence, and energy-line analysis.
"""

import configparser
import math
import os
import sqlite3
import subprocess

import numpy as np
import pytest


# ---------- Config parsing ----------

def load_config():
    cfg = configparser.ConfigParser()
    cfg.read("/app/dambreak.ini")

    def plist(s):
        return [float(x.strip()) for x in s.split("|")]

    return {
        "slope_angle_deg": cfg.getfloat("DAMBREAK", "slopeAngleDeg"),
        "friction_angle_deg": cfg.getfloat("DAMBREAK", "frictionAngleDeg"),
        "initial_height_m": cfg.getfloat("DAMBREAK", "initialHeightM"),
        "initial_column_x_min_m": cfg.getfloat("DAMBREAK", "columnXMinM"),
        "initial_column_x_max_m": cfg.getfloat("DAMBREAK", "columnXMaxM"),
        "earth_pressure_coeff": cfg.getfloat("DAMBREAK", "earthPressureCoeff"),
        "density_kg_m3": cfg.getfloat("DAMBREAK", "densityKgM3"),
        "gravity_m_s2": cfg.getfloat("GENERAL", "gravityMS2"),
        "time_steps_s": plist(cfg.get("OUTPUT", "timeStepsS")),
        "grid_resolutions_m": plist(cfg.get("OUTPUT", "gridResolutionsM")),
        "domain_x_min_m": cfg.getfloat("OUTPUT", "domainXMinM"),
        "domain_x_max_m": cfg.getfloat("OUTPUT", "domainXMaxM"),
        "domain_y_min_m": cfg.getfloat("OUTPUT", "domainYMinM"),
        "domain_y_max_m": cfg.getfloat("OUTPUT", "domainYMaxM"),
    }


# ---------- Raster helpers ----------

def parse_asc(filepath):
    """Parse an ESRI ASCII raster file. Returns (header_dict, np.ndarray)."""
    header = {}
    with open(filepath, "r") as f:
        for _ in range(6):
            parts = f.readline().strip().split(None, 1)
            key = parts[0].lower()
            val = parts[1].strip()
            try:
                header[key] = int(val)
            except ValueError:
                header[key] = float(val)
        data = []
        for line in f:
            vals = line.strip().split()
            if vals:
                data.append([float(v) for v in vals])
    cs = header.get("cellsize", 1)
    if "xllcenter" in header and "xllcorner" not in header:
        header["xllcorner"] = header["xllcenter"] - cs / 2.0
    if "yllcenter" in header and "yllcorner" not in header:
        header["yllcorner"] = header["yllcenter"] - cs / 2.0
    return header, np.array(data)


def fmt_res(r):
    return f"{int(r)}m" if r == int(r) else f"{r}m"


def fmt_time(t):
    return f"{int(t)}s" if t == int(t) else f"{t}s"


# ---------- Reference analytical solution ----------

def analytical_h_u(x, t, p):
    """Return (h, u) for the dam break at position x, time t."""
    h0, c0, a = p["h0"], p["c0"], p["a_net"]
    g_eff = p["g_eff"]
    x_col_min = p["x_col_min"]

    half_at2 = 0.5 * a * t * t
    x_left = x_col_min + half_at2
    x_A = -c0 * t + half_at2
    x_B = 2.0 * c0 * t + half_at2

    if x < x_left or x > x_B:
        return 0.0, 0.0
    if x <= x_A:
        return h0, a * t
    xi = (x - half_at2) / t
    h = (2.0 * c0 - xi) ** 2 / (9.0 * g_eff)
    u = (2.0 / 3.0) * (xi + c0) + a * t
    return h, u


# ---------- Fixtures ----------

@pytest.fixture(scope="session")
def config():
    return load_config()


@pytest.fixture(scope="session")
def phys(config):
    phi = math.radians(config["slope_angle_deg"])
    delta = math.radians(config["friction_angle_deg"])
    h0 = config["initial_height_m"]
    Kx = config["earth_pressure_coeff"]
    g = config["gravity_m_s2"]
    g_eff = Kx * g * math.cos(phi)
    mu = math.tan(delta)
    a_net = g * (math.sin(phi) - mu * math.cos(phi))
    c0 = math.sqrt(g_eff * h0)
    return {
        "phi": phi, "delta": delta, "h0": h0, "Kx": Kx, "g": g,
        "rho": config["density_kg_m3"],
        "g_eff": g_eff, "mu": mu, "a_net": a_net, "c0": c0,
        "x_col_min": config["initial_column_x_min_m"],
        "x_col_max": config["initial_column_x_max_m"],
    }


@pytest.fixture(scope="session")
def run_analysis():
    """Execute the dambreak analysis tool once for the whole test session."""
    result = subprocess.run(
        ["python3", "/app/dambreak_analysis.py"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=300,
    )
    return result


# ---------- Test: Execution ----------

class TestExecution:
    def test_tool_runs_successfully(self, run_analysis):
        assert run_analysis.returncode == 0, (
            f"Tool exited with code {run_analysis.returncode}.\n"
            f"stderr (last 800 chars):\n{run_analysis.stderr[-800:]}"
        )


# ---------- Test: Output File Existence ----------

class TestOutputFiles:
    def test_asc_files_exist(self, run_analysis, config):
        for r in config["grid_resolutions_m"]:
            rs = fmt_res(r)
            for t in config["time_steps_s"]:
                ts = fmt_time(t)
                for prefix in ("pft", "pfv"):
                    path = f"/app/output/{rs}/{prefix}_t{ts}.asc"
                    assert os.path.isfile(path), f"Missing: {path}"

    def test_geotiff_files_exist(self, run_analysis, config):
        for r in config["grid_resolutions_m"]:
            rs = fmt_res(r)
            for t in config["time_steps_s"]:
                ts = fmt_time(t)
                for prefix in ("pft", "pfv"):
                    path = f"/app/output/{rs}/{prefix}_t{ts}.tif"
                    assert os.path.isfile(path), f"Missing GeoTIFF: {path}"

    def test_sqlite_exists(self, run_analysis):
        assert os.path.isfile("/app/output/results.db"), "Missing results.db"


# ---------- Test: GeoTIFF Validation ----------

class TestGeoTIFF:
    def test_gdalinfo_readable(self, run_analysis, config):
        """Spot-check that a GeoTIFF is readable by gdalinfo."""
        rs = fmt_res(config["grid_resolutions_m"][1])
        ts = fmt_time(config["time_steps_s"][0])
        path = f"/app/output/{rs}/pft_t{ts}.tif"
        result = subprocess.run(
            ["gdalinfo", path], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"gdalinfo failed: {result.stderr}"
        assert "Size is" in result.stdout

    def test_geotiff_dimensions_match_asc(self, run_analysis, config):
        """GeoTIFF dimensions must match the corresponding ASC raster."""
        rs = fmt_res(config["grid_resolutions_m"][1])
        ts = fmt_time(config["time_steps_s"][0])

        header, _ = parse_asc(f"/app/output/{rs}/pft_t{ts}.asc")

        result = subprocess.run(
            ["gdalinfo", f"/app/output/{rs}/pft_t{ts}.tif"],
            capture_output=True, text=True, timeout=30
        )
        expected_size = f"Size is {header['ncols']}, {header['nrows']}"
        assert expected_size in result.stdout, (
            f"Expected '{expected_size}' in gdalinfo output"
        )

    def test_geotiff_values_match_asc(self, run_analysis, config):
        """GeoTIFF cell values must match ASC values."""
        rs = fmt_res(config["grid_resolutions_m"][1])
        ts = fmt_time(config["time_steps_s"][0])

        _, asc_data = parse_asc(f"/app/output/{rs}/pft_t{ts}.asc")

        tmp = "/tmp/_geotiff_check.asc"
        subprocess.run(
            ["gdal_translate", "-of", "AAIGrid", "-q",
             f"/app/output/{rs}/pft_t{ts}.tif", tmp],
            capture_output=True, timeout=30
        )
        _, tif_data = parse_asc(tmp)
        assert np.allclose(asc_data, tif_data, atol=1e-4), \
            "GeoTIFF values differ from ASC values"

    def test_geotiff_velocity_readable(self, run_analysis, config):
        """Velocity GeoTIFF should also be readable."""
        rs = fmt_res(config["grid_resolutions_m"][0])
        ts = fmt_time(config["time_steps_s"][-1])
        path = f"/app/output/{rs}/pfv_t{ts}.tif"
        result = subprocess.run(
            ["gdalinfo", path], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"gdalinfo failed on velocity TIF: {result.stderr}"


# ---------- Test: SQLite Database ----------

class TestSQLite:
    def test_convergence_table_exists(self, run_analysis):
        conn = sqlite3.connect("/app/output/results.db")
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='convergence'"
        )
        assert cur.fetchone() is not None, "Missing table 'convergence'"
        conn.close()

    def test_convergence_columns(self, run_analysis):
        conn = sqlite3.connect("/app/output/results.db")
        cur = conn.execute("PRAGMA table_info(convergence)")
        cols = {row[1] for row in cur.fetchall()}
        required = {"coarse_m", "fine_m", "time_s", "l2_pft", "lmax_pft"}
        assert required.issubset(cols), f"Missing columns: {required - cols}"
        conn.close()

    def test_convergence_row_count(self, run_analysis, config):
        conn = sqlite3.connect("/app/output/results.db")
        resolutions = sorted(config["grid_resolutions_m"], reverse=True)
        expected = (len(resolutions) - 1) * len(config["time_steps_s"])
        cur = conn.execute("SELECT COUNT(*) FROM convergence")
        count = cur.fetchone()[0]
        assert count == expected, f"Expected {expected} rows, got {count}"
        conn.close()

    def test_convergence_l2_positive(self, run_analysis):
        conn = sqlite3.connect("/app/output/results.db")
        cur = conn.execute("SELECT MIN(l2_pft), MIN(lmax_pft) FROM convergence")
        row = cur.fetchone()
        assert row[0] >= 0, "L2 must be non-negative"
        assert row[1] >= 0, "Lmax must be non-negative"
        conn.close()

    def test_convergence_l2_decreases(self, run_analysis, config):
        """For each time step, L2 of consecutive pairs should decrease."""
        conn = sqlite3.connect("/app/output/results.db")
        resolutions = sorted(config["grid_resolutions_m"], reverse=True)
        for t in config["time_steps_s"]:
            l2s = []
            for i in range(len(resolutions) - 1):
                rc, rf = resolutions[i], resolutions[i + 1]
                cur = conn.execute(
                    "SELECT l2_pft FROM convergence "
                    "WHERE abs(coarse_m - ?) < 0.01 AND abs(fine_m - ?) < 0.01 "
                    "AND abs(time_s - ?) < 0.01",
                    (rc, rf, t)
                )
                row = cur.fetchone()
                assert row is not None, f"Missing row for {rc}->{rf} at t={t}"
                l2s.append(row[0])
            assert len(l2s) >= 2, f"Not enough L2 values at t={t}"
            assert l2s[-1] < l2s[0], f"L2 not decreasing at t={t}: {l2s}"
        conn.close()

    def test_energy_line_table_exists(self, run_analysis):
        conn = sqlite3.connect("/app/output/results.db")
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='energy_line'"
        )
        assert cur.fetchone() is not None, "Missing table 'energy_line'"
        conn.close()

    def test_energy_line_keys(self, run_analysis):
        conn = sqlite3.connect("/app/output/results.db")
        cur = conn.execute("SELECT key FROM energy_line")
        keys = {row[0] for row in cur.fetchall()}
        required = {
            "runout_angle_deg", "theoretical_alpha_deg",
            "mass_center_x_m", "mass_center_z_m", "kinetic_altitude_m",
        }
        assert required.issubset(keys), f"Missing keys: {required - keys}"
        conn.close()

    def test_theoretical_alpha_equals_friction(self, run_analysis, config):
        conn = sqlite3.connect("/app/output/results.db")
        cur = conn.execute(
            "SELECT value FROM energy_line WHERE key='theoretical_alpha_deg'"
        )
        val = cur.fetchone()[0]
        assert abs(val - config["friction_angle_deg"]) < 0.1
        conn.close()

    def test_runout_angle_within_tolerance(self, run_analysis, config):
        conn = sqlite3.connect("/app/output/results.db")
        cur = conn.execute(
            "SELECT value FROM energy_line WHERE key='runout_angle_deg'"
        )
        val = cur.fetchone()[0]
        assert abs(val - config["friction_angle_deg"]) < 2.0, (
            f"Runout angle {val:.2f} not within 2° of {config['friction_angle_deg']}"
        )
        conn.close()

    def test_mass_center_downslope(self, run_analysis):
        conn = sqlite3.connect("/app/output/results.db")
        cur = conn.execute(
            "SELECT value FROM energy_line WHERE key='mass_center_x_m'"
        )
        assert cur.fetchone()[0] > 0, "Mass center should be downslope"
        cur = conn.execute(
            "SELECT value FROM energy_line WHERE key='mass_center_z_m'"
        )
        assert cur.fetchone()[0] < 0, "Mass center should be below origin"
        conn.close()

    def test_kinetic_altitude_positive(self, run_analysis):
        conn = sqlite3.connect("/app/output/results.db")
        cur = conn.execute(
            "SELECT value FROM energy_line WHERE key='kinetic_altitude_m'"
        )
        assert cur.fetchone()[0] > 0, "Material should have nonzero velocity"
        conn.close()


# ---------- Test: ESRI ASCII Raster Format ----------

class TestRasterFormat:
    def test_header_keys(self, run_analysis, config):
        r = config["grid_resolutions_m"][-1]
        t = config["time_steps_s"][0]
        header, _ = parse_asc(
            f"/app/output/{fmt_res(r)}/pft_t{fmt_time(t)}.asc"
        )
        required = {"ncols", "nrows", "cellsize", "nodata_value"}
        assert required.issubset(set(header.keys())), (
            f"Missing header keys: {required - set(header.keys())}"
        )
        assert "xllcorner" in header or "xllcenter" in header
        assert "yllcorner" in header or "yllcenter" in header

    def test_cellsize_matches_resolution(self, run_analysis, config):
        r = config["grid_resolutions_m"][1]  # 5m
        t = config["time_steps_s"][0]
        header, _ = parse_asc(f"/app/output/5m/pft_t{fmt_time(t)}.asc")
        assert header["cellsize"] == pytest.approx(r, abs=0.01)

    def test_data_dimensions_match_header(self, run_analysis):
        header, data = parse_asc("/app/output/5m/pft_t10s.asc")
        assert data.shape == (header["nrows"], header["ncols"])

    def test_domain_coverage(self, run_analysis, config):
        header, _ = parse_asc("/app/output/5m/pft_t10s.asc")
        cs = header["cellsize"]
        x_extent = header["ncols"] * cs
        y_extent = header["nrows"] * cs
        dx = config["domain_x_max_m"] - config["domain_x_min_m"]
        dy = config["domain_y_max_m"] - config["domain_y_min_m"]
        assert abs(x_extent - dx) <= cs
        assert abs(y_extent - dy) <= cs


# ---------- Test: Analytical Accuracy ----------

class TestAnalyticalAccuracy:
    def test_thickness_profile_5m_t10(self, run_analysis, phys):
        header, data = parse_asc("/app/output/5m/pft_t10s.asc")
        mid = header["nrows"] // 2
        h_row = data[mid]
        cs = header["cellsize"]
        xll = header["xllcorner"]
        max_err = 0.0
        count = 0
        for j in range(header["ncols"]):
            x = xll + (j + 0.5) * cs
            h_exp, _ = analytical_h_u(x, 10.0, phys)
            if h_exp > 0.05:
                err = abs(h_row[j] - h_exp) / h_exp
                max_err = max(max_err, err)
                count += 1
            else:
                assert h_row[j] < 0.15, f"x={x:.1f}: expected ~0, got {h_row[j]:.4f}"
        assert count > 20, "Too few flow cells found"
        assert max_err < 0.02, f"Max thickness rel-error {max_err:.4f} > 2%"

    def test_velocity_profile_5m_t10(self, run_analysis, phys):
        header_h, data_h = parse_asc("/app/output/5m/pft_t10s.asc")
        header_v, data_v = parse_asc("/app/output/5m/pfv_t10s.asc")
        mid = header_v["nrows"] // 2
        v_row = data_v[mid]
        cs = header_v["cellsize"]
        xll = header_v["xllcorner"]
        max_err = 0.0
        for j in range(header_v["ncols"]):
            x = xll + (j + 0.5) * cs
            h_exp, u_exp = analytical_h_u(x, 10.0, phys)
            if h_exp > 0.1 and u_exp > 0.5:
                err = abs(v_row[j] - u_exp) / u_exp
                max_err = max(max_err, err)
        assert max_err < 0.02, f"Max velocity rel-error {max_err:.4f} > 2%"

    def test_undisturbed_region_has_h0(self, run_analysis, phys):
        header, data = parse_asc("/app/output/5m/pft_t10s.asc")
        mid = header["nrows"] // 2
        cs = header["cellsize"]
        xll = header["xllcorner"]
        col_0 = int((0.0 - xll) / cs)
        if 0 <= col_0 < header["ncols"]:
            assert abs(data[mid][col_0] - phys["h0"]) < 0.05, (
                f"Undisturbed h={data[mid][col_0]:.4f}, expected {phys['h0']}"
            )

    def test_vacuum_ahead_of_front(self, run_analysis, phys):
        header, data = parse_asc("/app/output/5m/pft_t10s.asc")
        mid = header["nrows"] // 2
        cs = header["cellsize"]
        xll = header["xllcorner"]
        col = int((250.0 - xll) / cs)
        if 0 <= col < header["ncols"]:
            assert data[mid][col] < 0.01, f"Expected vacuum at x=250"

    def test_vacuum_behind_material(self, run_analysis, phys):
        header, data = parse_asc("/app/output/5m/pft_t10s.asc")
        mid = header["nrows"] // 2
        cs = header["cellsize"]
        xll = header["xllcorner"]
        col = int((-150.0 - xll) / cs)
        if 0 <= col < header["ncols"]:
            assert data[mid][col] < 0.01, f"Expected vacuum at x=-150"

    def test_thickness_at_t20(self, run_analysis, phys):
        header, data = parse_asc("/app/output/5m/pft_t20s.asc")
        mid = header["nrows"] // 2
        cs = header["cellsize"]
        xll = header["xllcorner"]
        errors = []
        for j in range(0, header["ncols"], 5):
            x = xll + (j + 0.5) * cs
            h_exp, _ = analytical_h_u(x, 20.0, phys)
            if h_exp > 0.1:
                errors.append(abs(data[mid][j] - h_exp) / h_exp)
        assert len(errors) > 10, "Too few flow cells at t=20s"
        assert max(errors) < 0.02, f"Max thickness error at t=20: {max(errors):.4f}"

    def test_rows_uniform(self, run_analysis):
        """Problem is 1D: all rows should be identical."""
        header, data = parse_asc("/app/output/5m/pft_t10s.asc")
        if header["nrows"] >= 2:
            row0 = data[0]
            for r in range(1, header["nrows"]):
                assert np.allclose(data[r], row0, atol=1e-6), (
                    f"Row {r} differs from row 0 — should be uniform in y"
                )


# ---------- Test: Mass Conservation ----------

class TestMassConservation:
    def test_mass_conserved_1m(self, run_analysis, config, phys):
        rho = phys["rho"]
        h0 = phys["h0"]
        L = phys["x_col_max"] - phys["x_col_min"]
        M_initial = rho * h0 * L

        for t in config["time_steps_s"]:
            ts = fmt_time(t)
            header, data = parse_asc(f"/app/output/1m/pft_t{ts}.asc")
            mid = header["nrows"] // 2
            h_row = data[mid]
            M_discrete = rho * float(np.sum(h_row)) * header["cellsize"]
            rel_err = abs(M_discrete - M_initial) / M_initial
            assert rel_err < 0.02, (
                f"Mass error at t={t}s (1m): {rel_err*100:.2f}% > 2%"
            )

    def test_mass_conserved_5m(self, run_analysis, config, phys):
        rho = phys["rho"]
        h0 = phys["h0"]
        L = phys["x_col_max"] - phys["x_col_min"]
        M_initial = rho * h0 * L

        for t in config["time_steps_s"]:
            ts = fmt_time(t)
            header, data = parse_asc(f"/app/output/5m/pft_t{ts}.asc")
            mid = header["nrows"] // 2
            h_row = data[mid]
            M_discrete = rho * float(np.sum(h_row)) * header["cellsize"]
            rel_err = abs(M_discrete - M_initial) / M_initial
            assert rel_err < 0.05, (
                f"Mass error at t={t}s (5m): {rel_err*100:.2f}% > 5%"
            )
