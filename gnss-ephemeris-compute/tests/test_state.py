
import json
import math
import os
import re
import sqlite3
from datetime import datetime, timedelta

# ---- Reference constants ----
MU_GPS = 3.986005e14
MU_GAL = 3.986004418e14
OMEGA_E_DOT = 7.2921151467e-5
C_LIGHT = 299792458.0

GPS_NOMINAL_RADIUS = 26560e3
GAL_NOMINAL_RADIUS = 29600e3

# ---- Reference ephemeris data (parsed from the RINEX files) ----
EPHEM_G06 = {
    "af0": -8.39701388031e-04, "af1": -1.65982783074e-11, "af2": 0.0,
    "IODE": 91.0, "Crs": 93.40625, "Delta_n": 1.16040547840e-09, "M0": 0.162092304801,
    "Cuc": 4.84101474285e-06, "e": 6.26740418375e-03, "Cus": 6.52112066746e-06,
    "sqrt_A": 5153.65489006,
    "Toe": 409904.0, "Cic": -2.42143869400e-08, "OMEGA0": 0.329237003460,
    "Cis": -5.96046447754e-08,
    "i0": 0.942817490922, "Crc": 326.593750, "omega": 2.06958726335,
    "OMEGA_DOT": -6.38312302555e-09,
    "IDOT": 3.07155651409e-10,
    "Toc_tow": 409904.0,
    "gps_week": 1025,
    "epoch_date": (1999, 9, 2, 17, 51, 44),
}

EPHEM_G13 = {
    "af0": 4.90025617182e-04, "af1": 2.04636307899e-12, "af2": 0.0,
    "IODE": 133.0, "Crs": -96.3125, "Delta_n": 1.46970407622e-09, "M0": 2.92961152146,
    "Cuc": -4.98816370964e-06, "e": 2.00239347760e-03, "Cus": 9.28156077862e-06,
    "sqrt_A": 5153.28476143,
    "Toe": 414000.0, "Cic": -2.79396772385e-08, "OMEGA0": 2.43031939942,
    "Cis": -5.58793544769e-08,
    "i0": 1.10192796930, "Crc": 271.1875, "omega": -2.32757915425,
    "OMEGA_DOT": -6.19632953057e-09,
    "IDOT": -7.85747015231e-12,
    "Toc_tow": 414000.0,
    "gps_week": 1025,
    "epoch_date": (1999, 9, 2, 19, 0, 0),
}

EPHEM_E12 = {
    "af0": -1.383925089613e-03, "af1": -1.314646169703e-10, "af2": 0.0,
    "IODE": 93.0, "Crs": -165.53125, "Delta_n": 2.857976189037e-09, "M0": 1.382758884589,
    "Cuc": -7.824972271919e-06, "e": 3.466791240498e-04, "Cus": 1.143850386143e-05,
    "sqrt_A": 5440.625097275,
    "Toe": 439800.0, "Cic": 2.980232238770e-08, "OMEGA0": -2.961851013120,
    "Cis": -1.117587089539e-08,
    "i0": 0.9656832940254, "Crc": 99.375, "omega": -0.6293609760051,
    "OMEGA_DOT": -5.415939881349e-09,
    "IDOT": -5.714523747137e-12,
    "Toc_tow": 439800.0,
    "gps_week": 1849,
    "epoch_date": (2015, 6, 19, 2, 10, 0),
}

EPHEM_E33 = {
    "af0": -1.383925089613e-03, "af1": -1.314646169703e-10, "af2": 0.0,
    "IODE": 93.0, "Crs": -165.53125, "Delta_n": 2.857976189037e-09, "M0": 1.382758884589,
    "Cuc": -7.824972271919e-06, "e": 3.466791240498e-04, "Cus": 1.143850386143e-05,
    "sqrt_A": 3000.0,
    "Toe": 439800.0, "Cic": 2.980232238770e-08, "OMEGA0": -2.961851013120,
    "Cis": -1.117587089539e-08,
    "i0": 0.9656832940254, "Crc": 99.375, "omega": -0.6293609760051,
    "OMEGA_DOT": -5.415939881349e-09,
    "IDOT": -5.714523747137e-12,
    "Toc_tow": 439800.0,
    "gps_week": 1849,
    "epoch_date": (2015, 6, 19, 2, 10, 0),
}


def _compute_sat_pos(eph, tow, constellation):
    """Reference implementation of broadcast ephemeris position algorithm."""
    mu = MU_GPS if constellation == "G" else MU_GAL

    A = eph["sqrt_A"] ** 2
    n0 = math.sqrt(mu / A**3)
    n = n0 + eph["Delta_n"]

    tk = tow - eph["Toe"]
    if tk > 302400:
        tk -= 604800
    elif tk < -302400:
        tk += 604800

    Mk = eph["M0"] + n * tk

    Ek = Mk
    for _ in range(30):
        Ek_new = Mk + eph["e"] * math.sin(Ek)
        if abs(Ek_new - Ek) < 1e-15:
            break
        Ek = Ek_new
    Ek = Ek_new

    sin_Ek = math.sin(Ek)
    cos_Ek = math.cos(Ek)

    denom = 1.0 - eph["e"] * cos_Ek
    sin_vk = math.sqrt(1.0 - eph["e"] ** 2) * sin_Ek / denom
    cos_vk = (cos_Ek - eph["e"]) / denom
    vk = math.atan2(sin_vk, cos_vk)

    Phi_k = vk + eph["omega"]

    sin2Phi = math.sin(2.0 * Phi_k)
    cos2Phi = math.cos(2.0 * Phi_k)

    delta_uk = eph["Cus"] * sin2Phi + eph["Cuc"] * cos2Phi
    delta_rk = eph["Crs"] * sin2Phi + eph["Crc"] * cos2Phi
    delta_ik = eph["Cis"] * sin2Phi + eph["Cic"] * cos2Phi

    uk = Phi_k + delta_uk
    rk = A * (1.0 - eph["e"] * cos_Ek) + delta_rk
    ik = eph["i0"] + delta_ik + eph["IDOT"] * tk

    xk_prime = rk * math.cos(uk)
    yk_prime = rk * math.sin(uk)

    OMEGA_k = (
        eph["OMEGA0"] + (eph["OMEGA_DOT"] - OMEGA_E_DOT) * tk - OMEGA_E_DOT * eph["Toe"]
    )

    cos_OMEGA = math.cos(OMEGA_k)
    sin_OMEGA = math.sin(OMEGA_k)
    cos_ik = math.cos(ik)
    sin_ik = math.sin(ik)

    xk = xk_prime * cos_OMEGA - yk_prime * cos_ik * sin_OMEGA
    yk = xk_prime * sin_OMEGA + yk_prime * cos_ik * cos_OMEGA
    zk = yk_prime * sin_ik

    dt_clk = tow - eph["Toc_tow"]
    if dt_clk > 302400:
        dt_clk -= 604800
    elif dt_clk < -302400:
        dt_clk += 604800

    clock_corr = eph["af0"] + eph["af1"] * dt_clk + eph["af2"] * dt_clk**2

    F = -2.0 * math.sqrt(mu) / (C_LIGHT**2)
    rel_corr = F * eph["e"] * eph["sqrt_A"] * sin_Ek

    return xk, yk, zk, clock_corr, rel_corr


def _gps_week_and_tow(year, month, day, hour, minute, second):
    """Compute GPS week and TOW from calendar date."""
    dt = datetime(year, month, day, hour, minute, second)
    gps_epoch = datetime(1980, 1, 6)
    total_seconds = (dt - gps_epoch).total_seconds()
    week = int(total_seconds // 604800)
    tow = total_seconds - week * 604800
    return week, tow


def _gps_to_calendar(gps_week, tow):
    """Convert GPS week + TOW to calendar date."""
    gps_epoch = datetime(1980, 1, 6)
    dt = gps_epoch + timedelta(seconds=gps_week * 604800 + tow)
    return dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second


def _compute_mjd(year, month, day):
    """Compute Modified Julian Day from calendar date."""
    y, m = year, month
    if m <= 2:
        y -= 1
        m += 12
    A = y // 100
    B = 2 - A + A // 4
    JD = int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + day + B - 1524.5
    return int(JD - 2400000.5)


# Satellite query times: Toe, Toe+300, Toe+600
SAT_QUERIES = {
    "G06": [409904.0, 410204.0, 410504.0],
    "G13": [414000.0, 414300.0, 414600.0],
    "E12": [439800.0, 440100.0, 440400.0],
    "E33": [439800.0, 440100.0, 440400.0],
}

EPHEM_MAP = {"G06": EPHEM_G06, "G13": EPHEM_G13, "E12": EPHEM_E12, "E33": EPHEM_E33}


# ===================== TESTS =====================

DB_PATH = "/app/output/gnss.db"
REPORT_PATH = "/app/output/report.json"
CONVERTED_PATH = "/app/output/converted.25n"
SP3_PATH = "/app/output/orbits.sp3"
VALIDATION_PATH = "/app/output/validation.json"


class TestSQLiteStructure:
    """Verify SQLite database structure and content."""

    def test_db_exists(self):
        assert os.path.isfile(DB_PATH), "SQLite database not found"

    def test_table_exists(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='positions'")
        result = c.fetchone()
        conn.close()
        assert result is not None, "positions table not found"

    def test_column_names(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("PRAGMA table_info(positions)")
        columns = {row[1] for row in c.fetchall()}
        conn.close()
        expected = {
            "satellite", "gps_week", "tow", "x_m", "y_m", "z_m",
            "clock_correction_s", "relativistic_correction_s",
            "orbit_radius_m", "anomaly_flag",
        }
        assert expected.issubset(columns), f"Missing columns: {expected - columns}"

    def test_record_count(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM positions")
        count = c.fetchone()[0]
        conn.close()
        assert count == 12, f"Expected 12 records, got {count}"

    def test_all_satellites_present(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT DISTINCT satellite FROM positions ORDER BY satellite")
        sats = [row[0] for row in c.fetchall()]
        conn.close()
        assert sats == ["E12", "E33", "G06", "G13"], f"Satellites: {sats}"

    def test_three_times_per_satellite(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        for sat, times in SAT_QUERIES.items():
            c.execute(
                "SELECT tow FROM positions WHERE satellite=? ORDER BY tow", (sat,)
            )
            rows = [row[0] for row in c.fetchall()]
            assert len(rows) == 3, f"{sat}: expected 3 times, got {len(rows)}"
            for expected_tow, actual_tow in zip(times, rows):
                assert abs(expected_tow - actual_tow) < 0.1, (
                    f"{sat}: expected tow {expected_tow}, got {actual_tow}"
                )
        conn.close()

    def test_gps_week_values(self):
        """GPS week must be correct for each satellite."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        for sat, expected_week in [("G06", 1025), ("G13", 1025), ("E12", 1849), ("E33", 1849)]:
            c.execute(
                "SELECT DISTINCT gps_week FROM positions WHERE satellite=?", (sat,)
            )
            weeks = [row[0] for row in c.fetchall()]
            assert len(weeks) == 1, f"{sat}: expected 1 gps_week, got {weeks}"
            assert weeks[0] == expected_week, (
                f"{sat}: expected gps_week {expected_week}, got {weeks[0]}"
            )
        conn.close()


class TestPositionAccuracy:
    """Verify computed positions against reference."""

    def setup_method(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.c = self.conn.cursor()

    def teardown_method(self):
        self.conn.close()

    def _get_row(self, sat, tow):
        self.c.execute(
            "SELECT x_m, y_m, z_m, clock_correction_s, relativistic_correction_s, "
            "orbit_radius_m, anomaly_flag FROM positions "
            "WHERE satellite=? AND ABS(tow - ?) < 0.1",
            (sat, tow),
        )
        return self.c.fetchone()

    def test_gps_positions(self):
        """GPS satellite positions must match reference within 0.01 m."""
        for sat in ["G06", "G13"]:
            eph = EPHEM_MAP[sat]
            for tow in SAT_QUERIES[sat]:
                ref_x, ref_y, ref_z, _, _ = _compute_sat_pos(eph, tow, "G")
                row = self._get_row(sat, tow)
                assert row is not None, f"Missing {sat}@{tow}"
                assert abs(row[0] - ref_x) < 0.01, f"{sat}@{tow}: x_m off by {abs(row[0]-ref_x)}"
                assert abs(row[1] - ref_y) < 0.01, f"{sat}@{tow}: y_m off by {abs(row[1]-ref_y)}"
                assert abs(row[2] - ref_z) < 0.01, f"{sat}@{tow}: z_m off by {abs(row[2]-ref_z)}"

    def test_galileo_e12_positions(self):
        """Galileo E12 positions must match reference within 0.01 m."""
        for tow in SAT_QUERIES["E12"]:
            ref_x, ref_y, ref_z, _, _ = _compute_sat_pos(EPHEM_E12, tow, "E")
            row = self._get_row("E12", tow)
            assert row is not None, f"Missing E12@{tow}"
            assert abs(row[0] - ref_x) < 0.01, f"E12@{tow}: x_m off by {abs(row[0]-ref_x)}"
            assert abs(row[1] - ref_y) < 0.01, f"E12@{tow}: y_m off by {abs(row[1]-ref_y)}"
            assert abs(row[2] - ref_z) < 0.01, f"E12@{tow}: z_m off by {abs(row[2]-ref_z)}"

    def test_clock_corrections(self):
        """Clock corrections for non-anomalous satellites within 1e-12 s."""
        for sat, const in [("G06", "G"), ("G13", "G"), ("E12", "E")]:
            eph = EPHEM_MAP[sat]
            for tow in SAT_QUERIES[sat]:
                _, _, _, ref_clk, _ = _compute_sat_pos(eph, tow, const)
                row = self._get_row(sat, tow)
                assert row is not None
                assert abs(row[3] - ref_clk) < 1e-12, (
                    f"{sat}@{tow}: clock off by {abs(row[3]-ref_clk):.2e}"
                )

    def test_relativistic_corrections(self):
        """Relativistic corrections for non-anomalous satellites within 1e-12 s."""
        for sat, const in [("G06", "G"), ("G13", "G"), ("E12", "E")]:
            eph = EPHEM_MAP[sat]
            for tow in SAT_QUERIES[sat]:
                _, _, _, _, ref_rel = _compute_sat_pos(eph, tow, const)
                row = self._get_row(sat, tow)
                assert row is not None
                assert abs(row[4] - ref_rel) < 1e-12, (
                    f"{sat}@{tow}: relativistic off by {abs(row[4]-ref_rel):.2e}"
                )

    def test_orbit_radius_consistency(self):
        """orbit_radius_m must equal sqrt(x^2 + y^2 + z^2)."""
        self.c.execute("SELECT satellite, tow, x_m, y_m, z_m, orbit_radius_m FROM positions")
        for sat, tow, x, y, z, r in self.c.fetchall():
            computed_r = math.sqrt(x**2 + y**2 + z**2)
            assert abs(r - computed_r) < 0.01, (
                f"{sat}@{tow}: radius {r} != computed {computed_r}"
            )

    def test_galileo_uses_correct_mu(self):
        """E12 positions at non-zero tk must use Galileo mu, not GPS mu."""
        offset_tows = [t for t in SAT_QUERIES["E12"] if t != EPHEM_E12["Toe"]]
        assert len(offset_tows) >= 1, "Need at least one offset time to test mu"
        for tow in offset_tows:
            ref_gal_x, ref_gal_y, ref_gal_z, _, _ = _compute_sat_pos(EPHEM_E12, tow, "E")
            ref_gps_x, ref_gps_y, ref_gps_z, _, _ = _compute_sat_pos(EPHEM_E12, tow, "G")
            row = self._get_row("E12", tow)
            assert row is not None
            err_gal = math.sqrt(
                (row[0] - ref_gal_x) ** 2
                + (row[1] - ref_gal_y) ** 2
                + (row[2] - ref_gal_z) ** 2
            )
            err_gps = math.sqrt(
                (row[0] - ref_gps_x) ** 2
                + (row[1] - ref_gps_y) ** 2
                + (row[2] - ref_gps_z) ** 2
            )
            assert err_gal < err_gps, f"E12@{tow}: appears to use GPS mu"

    def test_gps_orbit_radius_range(self):
        """GPS orbit radii must be in valid range."""
        self.c.execute(
            "SELECT satellite, tow, orbit_radius_m FROM positions WHERE satellite LIKE 'G%'"
        )
        for sat, tow, r in self.c.fetchall():
            assert 24000e3 < r < 28000e3, f"{sat}@{tow}: radius {r/1e3:.0f} km"

    def test_galileo_e12_orbit_radius_range(self):
        """Galileo E12 orbit radii must be in valid range."""
        self.c.execute(
            "SELECT tow, orbit_radius_m FROM positions WHERE satellite='E12'"
        )
        for tow, r in self.c.fetchall():
            assert 27000e3 < r < 32000e3, f"E12@{tow}: radius {r/1e3:.0f} km"


class TestAnomalyDetection:
    """Verify anomaly detection for corrupted satellite."""

    def setup_method(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.c = self.conn.cursor()

    def teardown_method(self):
        self.conn.close()

    def test_e33_all_flagged_anomalous(self):
        """All E33 positions must have anomaly_flag = 1."""
        self.c.execute("SELECT anomaly_flag FROM positions WHERE satellite='E33'")
        flags = [row[0] for row in self.c.fetchall()]
        assert len(flags) == 3, f"Expected 3 E33 records, got {len(flags)}"
        assert all(f == 1 for f in flags), f"E33 flags: {flags}"

    def test_gps_not_anomalous(self):
        """GPS satellites must have anomaly_flag = 0."""
        self.c.execute("SELECT anomaly_flag FROM positions WHERE satellite LIKE 'G%'")
        flags = [row[0] for row in self.c.fetchall()]
        assert len(flags) == 6
        assert all(f == 0 for f in flags), "GPS satellites should not be anomalous"

    def test_e12_not_anomalous(self):
        """E12 must have anomaly_flag = 0."""
        self.c.execute("SELECT anomaly_flag FROM positions WHERE satellite='E12'")
        flags = [row[0] for row in self.c.fetchall()]
        assert len(flags) == 3
        assert all(f == 0 for f in flags), "E12 should not be anomalous"

    def test_e33_orbit_radius_outside_range(self):
        """E33 orbit radius must be outside Galileo valid range."""
        self.c.execute(
            "SELECT orbit_radius_m FROM positions WHERE satellite='E33'"
        )
        for (r,) in self.c.fetchall():
            assert r < 27000e3 or r > 32000e3, (
                f"E33 radius {r/1e3:.0f} km unexpectedly in valid range"
            )


class TestReport:
    """Verify JSON integrity report."""

    def setup_method(self):
        with open(REPORT_PATH) as f:
            self.report = json.load(f)

    def test_report_exists(self):
        assert os.path.isfile(REPORT_PATH)

    def test_satellites_processed(self):
        assert self.report["satellites_processed"] == ["E12", "E33", "G06", "G13"]

    def test_total_positions(self):
        assert self.report["total_positions"] == 12

    def test_anomalous_satellites(self):
        assert self.report["anomalous_satellites"] == ["E33"]

    def test_rms_keys(self):
        rms = self.report["rms_radius_deviation"]
        assert "G06" in rms
        assert "G13" in rms
        assert "E12" in rms
        assert "E33" not in rms, "E33 (anomalous) should not have RMS entry"

    def test_rms_values_reasonable(self):
        """RMS deviations should be positive and below 1000 km for valid sats."""
        for sat, val in self.report["rms_radius_deviation"].items():
            assert 0 < val < 1000e3, f"{sat} RMS deviation {val} out of range"

    def test_rms_values_accurate(self):
        """Verify RMS values against reference computation."""
        for sat, const in [("G06", "G"), ("G13", "G"), ("E12", "E")]:
            eph = EPHEM_MAP[sat]
            nominal = GPS_NOMINAL_RADIUS if const == "G" else GAL_NOMINAL_RADIUS
            deviations = []
            for tow in SAT_QUERIES[sat]:
                x, y, z, _, _ = _compute_sat_pos(eph, tow, const)
                r = math.sqrt(x**2 + y**2 + z**2)
                deviations.append(r - nominal)
            ref_rms = math.sqrt(sum(d**2 for d in deviations) / len(deviations))
            actual_rms = self.report["rms_radius_deviation"][sat]
            assert abs(actual_rms - ref_rms) < 1.0, (
                f"{sat} RMS: expected {ref_rms:.1f}, got {actual_rms:.1f}"
            )


class TestFormatConversion:
    """Verify RINEX 2.11 to 3.05 conversion."""

    def test_converted_file_exists(self):
        assert os.path.isfile(CONVERTED_PATH), "Converted file not found"

    def test_version_line(self):
        with open(CONVERTED_PATH) as f:
            first_line = f.readline()
        assert "3.05" in first_line[:9], "Version should be 3.05"
        label = first_line[60:80].strip()
        assert label == "RINEX VERSION / TYPE", f"Wrong label: {label}"
        assert "G" in first_line[40:41], "Missing GPS system identifier"

    def test_header_labels_at_columns_61_80(self):
        required_labels = {
            "RINEX VERSION / TYPE",
            "PGM / RUN BY / DATE",
            "IONOSPHERIC CORR",
            "TIME SYSTEM CORR",
            "LEAP SECONDS",
            "END OF HEADER",
        }
        found_labels = set()
        with open(CONVERTED_PATH) as f:
            for line in f:
                if len(line.rstrip()) >= 60:
                    label = line[60:80].strip()
                    if label in required_labels:
                        found_labels.add(label)
                if "END OF HEADER" in line:
                    break
        assert found_labels == required_labels, (
            f"Missing labels: {required_labels - found_labels}"
        )

    def test_ionospheric_corr_format(self):
        """ION ALPHA/BETA must become IONOSPHERIC CORR with GPSA/GPSB."""
        found_gpsa = False
        found_gpsb = False
        with open(CONVERTED_PATH) as f:
            for line in f:
                if "END OF HEADER" in line:
                    break
                label = line[60:80].strip() if len(line.rstrip()) >= 60 else ""
                if label == "IONOSPHERIC CORR":
                    if line[:4] == "GPSA":
                        found_gpsa = True
                    elif line[:4] == "GPSB":
                        found_gpsb = True
        assert found_gpsa, "Missing GPSA IONOSPHERIC CORR record"
        assert found_gpsb, "Missing GPSB IONOSPHERIC CORR record"

    def test_time_system_corr(self):
        """DELTA-UTC must become TIME SYSTEM CORR with GPUT prefix."""
        found = False
        with open(CONVERTED_PATH) as f:
            for line in f:
                if "END OF HEADER" in line:
                    break
                label = line[60:80].strip() if len(line.rstrip()) >= 60 else ""
                if label == "TIME SYSTEM CORR" and line[:4] == "GPUT":
                    found = True
        assert found, "Missing GPUT TIME SYSTEM CORR record"

    def test_epoch_format_4digit_year_g_prefix(self):
        """Satellite epochs must use 4-digit years and G prefix."""
        in_data = False
        epochs_found = 0
        with open(CONVERTED_PATH) as f:
            for line in f:
                if "END OF HEADER" in line:
                    in_data = True
                    continue
                if not in_data:
                    continue
                if len(line) > 3 and line[0] == "G":
                    parts = line.split()
                    if len(parts) >= 7:
                        assert parts[0][0] == "G", f"Missing G prefix: {parts[0]}"
                        assert len(parts[1]) == 4, f"Year not 4-digit: {parts[1]}"
                        assert int(parts[1]) >= 1980, f"Year out of range: {parts[1]}"
                        epochs_found += 1
        assert epochs_found == 2, f"Expected 2 satellite epochs, found {epochs_found}"

    def test_broadcast_orbit_indentation(self):
        """V3.05 broadcast orbits must have at least 4-space indent."""
        in_data = False
        indent_ok = True
        orbit_lines = 0
        with open(CONVERTED_PATH) as f:
            for line in f:
                if "END OF HEADER" in line:
                    in_data = True
                    continue
                if not in_data:
                    continue
                if (
                    len(line) > 4
                    and line[0] == " "
                    and line.lstrip()[0] in ".-0123456789"
                ):
                    orbit_lines += 1
                    stripped = line.lstrip(" ")
                    indent = len(line) - len(stripped)
                    if indent < 4:
                        indent_ok = False
        assert orbit_lines >= 14, f"Expected >=14 orbit lines, found {orbit_lines}"
        assert indent_ok, "Broadcast orbit lines must have at least 4-space indent"

    def test_leap_seconds_preserved(self):
        found = False
        with open(CONVERTED_PATH) as f:
            for line in f:
                if "END OF HEADER" in line:
                    break
                label = line[60:80].strip() if len(line.rstrip()) >= 60 else ""
                if label == "LEAP SECONDS":
                    val = int(line[:6].strip())
                    assert val == 13, f"Leap seconds should be 13, got {val}"
                    found = True
        assert found, "Missing LEAP SECONDS record"

    def test_converted_data_preservation(self):
        """Parse G06 from converted file and verify a key ephemeris value."""
        in_data = False
        g06_lines = []
        collecting = False
        with open(CONVERTED_PATH) as f:
            for line in f:
                if "END OF HEADER" in line:
                    in_data = True
                    continue
                if not in_data:
                    continue
                if line.startswith("G06"):
                    collecting = True
                    g06_lines = [line]
                    continue
                if collecting:
                    g06_lines.append(line)
                    if len(g06_lines) == 8:
                        break

        assert len(g06_lines) == 8, "Could not find G06 with 8 lines in converted file"

        bo1 = re.sub(r"[Dd]", "E", g06_lines[1].strip())
        vals = bo1.split()
        iode = float(vals[0])
        assert abs(iode - 91.0) < 0.1, f"G06 IODE should be 91.0, got {iode}"


class TestSP3Export:
    """Verify SP3c format output."""

    def test_sp3_exists(self):
        assert os.path.isfile(SP3_PATH), "SP3 file not found"

    def test_header_structure(self):
        """SP3c header must have 22 lines with correct prefix sequence."""
        with open(SP3_PATH) as f:
            lines = f.readlines()
        assert len(lines) >= 22, f"SP3 file too short: {len(lines)} lines"
        # Version line
        assert lines[0][:2] in ("#c", "#d"), f"Line 1 must start with #c or #d: {lines[0][:5]}"
        assert lines[0][2] in ("P", "V"), f"Line 1 col 3 must be P or V: {lines[0][2]}"
        # GPS week line
        assert lines[1][:2] == "##", f"Line 2 must start with ##: {lines[1][:5]}"
        # 5 satellite list lines
        for i in range(2, 7):
            assert lines[i][0] == "+", f"Line {i+1} must start with +: {lines[i][:5]}"
        # 5 accuracy lines
        for i in range(7, 12):
            assert lines[i][:2] == "++", f"Line {i+1} must start with ++: {lines[i][:5]}"
        # 2 %c, 2 %f, 2 %i
        assert lines[12][:2] == "%c"
        assert lines[13][:2] == "%c"
        assert lines[14][:2] == "%f"
        assert lines[15][:2] == "%f"
        assert lines[16][:2] == "%i"
        assert lines[17][:2] == "%i"
        # 4 comment lines
        for i in range(18, 22):
            assert lines[i][:2] == "/*", f"Line {i+1} must be comment: {lines[i][:5]}"

    def test_version_line_epoch_count(self):
        """Version line must have correct epoch count."""
        with open(SP3_PATH) as f:
            line = f.readline()
        # epoch count at columns 33-39 (0-indexed 32:39)
        n_epochs = int(line[32:39].strip())
        assert n_epochs == 9, f"Expected 9 epochs, got {n_epochs}"

    def test_gps_week_and_sow(self):
        """## line must have correct GPS week and seconds of week."""
        with open(SP3_PATH) as f:
            f.readline()
            line = f.readline()
        parts = line[2:].split()
        gps_week = int(parts[0])
        sow = float(parts[1])
        assert gps_week == 1025, f"Expected GPS week 1025, got {gps_week}"
        assert abs(sow - 409904.0) < 0.01, f"Expected SOW 409904.0, got {sow}"

    def test_epoch_interval(self):
        """## line must specify 300s epoch interval."""
        with open(SP3_PATH) as f:
            f.readline()
            line = f.readline()
        parts = line[2:].split()
        interval = float(parts[2])
        assert abs(interval - 300.0) < 0.01, f"Expected interval 300.0, got {interval}"

    def test_mjd_value(self):
        """## line must contain correct MJD for first epoch date."""
        with open(SP3_PATH) as f:
            f.readline()
            line = f.readline()
        parts = line[2:].split()
        mjd = int(parts[3])
        # MJD of 1999-09-02
        expected_mjd = _compute_mjd(1999, 9, 2)
        assert mjd == expected_mjd, f"Expected MJD {expected_mjd}, got {mjd}"

    def test_satellite_count(self):
        """First + line must report 3 non-anomalous satellites."""
        with open(SP3_PATH) as f:
            lines = f.readlines()
        # First + line (index 2)
        count_str = lines[2][1:6].strip()
        n_sats = int(count_str)
        assert n_sats == 3, f"Expected 3 satellites, got {n_sats}"

    def test_satellite_ids_present(self):
        """SP3 satellite list must contain G06, G13, E12 but not E33."""
        with open(SP3_PATH) as f:
            content = f.read()
        for sat in ["G06", "G13", "E12"]:
            assert sat in content, f"{sat} missing from SP3 file"
        assert "E33" not in content, "Anomalous E33 should not be in SP3"

    def test_time_system_gps(self):
        """First %c line must specify GPS time system."""
        with open(SP3_PATH) as f:
            lines = f.readlines()
        assert "GPS" in lines[12], "First %c line must specify GPS time system"

    def test_eof_terminator(self):
        """SP3 file must end with EOF."""
        with open(SP3_PATH) as f:
            lines = f.readlines()
        assert lines[-1].strip() == "EOF", f"Last line must be EOF, got: {lines[-1].strip()}"

    def test_epoch_header_count(self):
        """Must have 9 epoch headers (3 sats x 3 times)."""
        count = 0
        with open(SP3_PATH) as f:
            for line in f:
                if line.startswith("*"):
                    count += 1
        assert count == 9, f"Expected 9 epoch headers, got {count}"

    def test_position_record_count(self):
        """Must have 9 position records (3 sats x 3 times)."""
        count = 0
        with open(SP3_PATH) as f:
            for line in f:
                if line.startswith("P"):
                    count += 1
        assert count == 9, f"Expected 9 position records, got {count}"

    def test_position_xyz_in_km(self):
        """SP3 XYZ values must be in km, matching reference positions."""
        sp3_positions = {}
        current_tow = None
        with open(SP3_PATH) as f:
            for line in f:
                if line.startswith("*"):
                    parts = line[2:].split()
                    yr, mo, dy = int(parts[0]), int(parts[1]), int(parts[2])
                    hr, mn = int(parts[3]), int(parts[4])
                    sc = int(float(parts[5]))
                    _, tow = _gps_week_and_tow(yr, mo, dy, hr, mn, sc)
                    current_tow = tow
                elif line.startswith("P") and current_tow is not None:
                    sat = line[1:4].strip()
                    vals = line[4:].split()
                    sp3_positions[(sat, current_tow)] = (
                        float(vals[0]), float(vals[1]), float(vals[2])
                    )

        for sat in ["G06", "G13", "E12"]:
            eph = EPHEM_MAP[sat]
            const = sat[0]
            for tow in SAT_QUERIES[sat]:
                ref_x, ref_y, ref_z, _, _ = _compute_sat_pos(eph, tow, const)
                key = (sat, tow)
                assert key in sp3_positions, f"Missing {sat}@{tow} in SP3"
                sp3_x, sp3_y, sp3_z = sp3_positions[key]
                assert abs(sp3_x - ref_x / 1000) < 0.001, (
                    f"{sat}@{tow}: x_km off by {abs(sp3_x - ref_x/1000):.6f}"
                )
                assert abs(sp3_y - ref_y / 1000) < 0.001, (
                    f"{sat}@{tow}: y_km off by {abs(sp3_y - ref_y/1000):.6f}"
                )
                assert abs(sp3_z - ref_z / 1000) < 0.001, (
                    f"{sat}@{tow}: z_km off by {abs(sp3_z - ref_z/1000):.6f}"
                )

    def test_clock_in_microseconds(self):
        """SP3 clock values must be in microseconds, matching reference."""
        sp3_clocks = {}
        current_tow = None
        with open(SP3_PATH) as f:
            for line in f:
                if line.startswith("*"):
                    parts = line[2:].split()
                    yr, mo, dy = int(parts[0]), int(parts[1]), int(parts[2])
                    hr, mn = int(parts[3]), int(parts[4])
                    sc = int(float(parts[5]))
                    _, tow = _gps_week_and_tow(yr, mo, dy, hr, mn, sc)
                    current_tow = tow
                elif line.startswith("P") and current_tow is not None:
                    sat = line[1:4].strip()
                    vals = line[4:].split()
                    sp3_clocks[(sat, current_tow)] = float(vals[3])

        for sat in ["G06", "G13", "E12"]:
            eph = EPHEM_MAP[sat]
            const = sat[0]
            for tow in SAT_QUERIES[sat]:
                _, _, _, ref_clk, _ = _compute_sat_pos(eph, tow, const)
                ref_clk_us = ref_clk * 1e6
                key = (sat, tow)
                assert key in sp3_clocks, f"Missing {sat}@{tow} clock in SP3"
                assert abs(sp3_clocks[key] - ref_clk_us) < 0.001, (
                    f"{sat}@{tow}: clock_us off by {abs(sp3_clocks[key]-ref_clk_us):.6f}"
                )

    def test_epoch_calendar_dates(self):
        """SP3 epoch headers must have correct calendar dates derived from GPS time."""
        epoch_dates = []
        with open(SP3_PATH) as f:
            for line in f:
                if line.startswith("*"):
                    parts = line[2:].split()
                    epoch_dates.append((int(parts[0]), int(parts[1]), int(parts[2]),
                                        int(parts[3]), int(parts[4])))

        # G06 epochs should be 1999-09-02
        assert (1999, 9, 2, 17, 51) in epoch_dates, "Missing G06 Toe epoch"
        assert (1999, 9, 2, 17, 56) in epoch_dates, "Missing G06 Toe+300 epoch"
        assert (1999, 9, 2, 18, 1) in epoch_dates, "Missing G06 Toe+600 epoch"
        # G13 epochs should be 1999-09-02
        assert (1999, 9, 2, 19, 0) in epoch_dates, "Missing G13 Toe epoch"
        # E12 epochs should be 2015-06-19
        assert (2015, 6, 19, 2, 10) in epoch_dates, "Missing E12 Toe epoch"


class TestValidation:
    """Verify cross-validation output."""

    def test_validation_exists(self):
        assert os.path.isfile(VALIDATION_PATH), "Validation JSON not found"

    def test_validation_structure(self):
        """Validation JSON must have required top-level keys."""
        with open(VALIDATION_PATH) as f:
            data = json.load(f)
        assert "satellites" in data, "Missing 'satellites' key"
        assert "overall_pass" in data, "Missing 'overall_pass' key"

    def test_validation_satellites(self):
        """Validation must cover G06, G13, E12 but not E33."""
        with open(VALIDATION_PATH) as f:
            data = json.load(f)
        sats = data["satellites"]
        for s in ["G06", "G13", "E12"]:
            assert s in sats, f"Missing satellite {s} in validation"
        assert "E33" not in sats, "Anomalous E33 should not be in validation"

    def test_satellite_fields(self):
        """Each satellite entry must have all required fields."""
        with open(VALIDATION_PATH) as f:
            data = json.load(f)
        required = {"sp3_match", "max_position_error_km", "velocities_km_s",
                     "velocity_anomaly", "clock_drift_rates", "clock_drift_anomaly"}
        for sat, entry in data["satellites"].items():
            missing = required - set(entry.keys())
            assert not missing, f"{sat} missing fields: {missing}"

    def test_sp3_match_true(self):
        """All satellites must have sp3_match = true."""
        with open(VALIDATION_PATH) as f:
            data = json.load(f)
        for sat, entry in data["satellites"].items():
            assert entry["sp3_match"] is True, f"{sat} sp3_match should be true"

    def test_max_position_error_small(self):
        """Position errors must be < 0.001 km."""
        with open(VALIDATION_PATH) as f:
            data = json.load(f)
        for sat, entry in data["satellites"].items():
            assert entry["max_position_error_km"] < 0.001, (
                f"{sat} position error too large: {entry['max_position_error_km']}"
            )

    def test_velocity_count(self):
        """Each satellite must have 2 velocity values (from 3 consecutive epochs)."""
        with open(VALIDATION_PATH) as f:
            data = json.load(f)
        for sat, entry in data["satellites"].items():
            assert len(entry["velocities_km_s"]) == 2, (
                f"{sat}: expected 2 velocities, got {len(entry['velocities_km_s'])}"
            )

    def test_velocity_range(self):
        """Velocities must be physically plausible (2.0-5.0 km/s)."""
        with open(VALIDATION_PATH) as f:
            data = json.load(f)
        for sat, entry in data["satellites"].items():
            for v in entry["velocities_km_s"]:
                assert 2.0 < v < 5.0, f"{sat}: velocity {v} km/s out of range"

    def test_velocity_accuracy(self):
        """Velocity values must match reference computation."""
        with open(VALIDATION_PATH) as f:
            data = json.load(f)
        for sat in ["G06", "G13", "E12"]:
            eph = EPHEM_MAP[sat]
            const = sat[0]
            tows = SAT_QUERIES[sat]
            ref_velocities = []
            positions = []
            for tow in tows:
                x, y, z, _, _ = _compute_sat_pos(eph, tow, const)
                positions.append((x, y, z))
            for i in range(1, len(positions)):
                dx = positions[i][0] - positions[i-1][0]
                dy = positions[i][1] - positions[i-1][1]
                dz = positions[i][2] - positions[i-1][2]
                dt = tows[i] - tows[i-1]
                v = math.sqrt(dx**2 + dy**2 + dz**2) / dt / 1000.0
                ref_velocities.append(v)
            actual_velocities = data["satellites"][sat]["velocities_km_s"]
            for ref_v, act_v in zip(ref_velocities, actual_velocities):
                assert abs(ref_v - act_v) < 0.01, (
                    f"{sat}: velocity mismatch ref={ref_v:.4f} act={act_v:.4f}"
                )

    def test_no_velocity_anomaly(self):
        """Non-anomalous satellites should have no velocity anomalies."""
        with open(VALIDATION_PATH) as f:
            data = json.load(f)
        for sat, entry in data["satellites"].items():
            assert entry["velocity_anomaly"] is False, (
                f"{sat} should not have velocity anomaly"
            )

    def test_clock_drift_count(self):
        """Each satellite must have 2 clock drift rate values."""
        with open(VALIDATION_PATH) as f:
            data = json.load(f)
        for sat, entry in data["satellites"].items():
            assert len(entry["clock_drift_rates"]) == 2, (
                f"{sat}: expected 2 drift rates, got {len(entry['clock_drift_rates'])}"
            )

    def test_clock_drift_small(self):
        """Clock drift rates must be much less than 1e-6 s/s."""
        with open(VALIDATION_PATH) as f:
            data = json.load(f)
        for sat, entry in data["satellites"].items():
            for rate in entry["clock_drift_rates"]:
                assert abs(rate) < 1e-6, (
                    f"{sat}: clock drift rate {rate} exceeds threshold"
                )

    def test_no_clock_drift_anomaly(self):
        """Non-anomalous satellites should have no clock drift anomalies."""
        with open(VALIDATION_PATH) as f:
            data = json.load(f)
        for sat, entry in data["satellites"].items():
            assert entry["clock_drift_anomaly"] is False, (
                f"{sat} should not have clock drift anomaly"
            )

    def test_overall_pass(self):
        """Overall validation must pass."""
        with open(VALIDATION_PATH) as f:
            data = json.load(f)
        assert data["overall_pass"] is True, "Overall validation should pass"
