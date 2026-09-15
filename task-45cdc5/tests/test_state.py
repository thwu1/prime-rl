"""
PSHA hazard curve verification tests.

Independent reference implementation reads from GeoJSON (fault sources),
NetCDF (gridded seismicity), SQLite (GMM coefficients), and YAML (config),
applies known data quality corrections, and compares against agent output.

"""

import csv
import json
import math
import os
import re
import sqlite3
import subprocess

import pytest
import yaml

GEOJSON_PATH = "/app/data/fault_sources.geojson"
NC_PATH = "/app/data/grid_seismicity.nc"
DB_PATH = "/app/data/model.db"
CONFIG_PATH = "/app/data/calc_config.yaml"
OUTPUT_CSV = "/app/output/hazard_curve.csv"
REPORT_FILE = "/app/output/validation_report.txt"


# ──────────────────────────────────────────────────────────────────────
# NetCDF reader via ncdump CLI
# ──────────────────────────────────────────────────────────────────────


def _nc_vars(path, names):
    """Extract 1D variable arrays from a NetCDF file using ncdump."""
    result = subprocess.run(
        ["ncdump", "-v", ",".join(names), path],
        capture_output=True, text=True, check=True,
    )
    text = result.stdout
    di = text.find("data:")
    assert di >= 0, "No data section in ncdump output"
    ds = text[di:]
    out = {}
    for v in names:
        m = re.search(rf"\b{v}\s*=\s*(.*?)\s*;", ds, re.DOTALL)
        assert m, f"Variable {v} not found in ncdump data section"
        out[v] = [float(x.strip()) for x in m.group(1).split(",") if x.strip()]
    return out


# ──────────────────────────────────────────────────────────────────────
# PSHA math functions (reference implementation)
# ──────────────────────────────────────────────────────────────────────


def _phi(x):
    return 0.5 * (1.0 + math.erf(x / 1.4142135623730951))


def _fe_dx(lon1, lon2, lat_r):
    return (lon2 - lon1) * math.cos(lat_r * math.pi / 180.0) * 111.195


def _fe_dy(lat1, lat2):
    return (lat2 - lat1) * 111.195


def _pt_seg_d(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    sq = vx * vx + vy * vy
    if sq < 1e-15:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / sq))
    return math.hypot(px - (ax + t * vx), py - (ay + t * vy))


def _pt_in_poly(px, py, poly):
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and (
            px < (xj - xi) * (py - yi) / (yj - yi) + xi
        ):
            inside = not inside
        j = i
    return inside


def _pt_poly_d(px, py, poly):
    if _pt_in_poly(px, py, poly):
        return 0.0
    md = float("inf")
    n = len(poly)
    for i in range(n):
        j = (i + 1) % n
        d = _pt_seg_d(px, py, poly[i][0], poly[i][1], poly[j][0], poly[j][1])
        if d < md:
            md = d
    return md


def _rjb(slon, slat, trace, dip, ddir, width):
    tl = [(_fe_dx(slon, ln, slat), _fe_dy(slat, lt)) for ln, lt in trace]
    if abs(dip - 90.0) < 1e-6:
        md = float("inf")
        for i in range(len(tl) - 1):
            d = _pt_seg_d(0, 0, tl[i][0], tl[i][1], tl[i + 1][0], tl[i + 1][1])
            if d < md:
                md = d
        return md
    h = width * math.cos(dip * math.pi / 180.0)
    dd = {"N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0)}[ddir]
    ext = [(x + dd[0] * h, y + dd[1] * h) for x, y in tl]
    poly = list(tl) + list(reversed(ext))
    return _pt_poly_d(0, 0, poly)


def _rhyp(slon, slat, lon, lat, dep):
    dx = _fe_dx(slon, lon, slat)
    dy = _fe_dy(slat, lat)
    rh = math.hypot(dx, dy)
    return math.hypot(rh, dep)


def _gr_rates(a, b, mmin, mmax, dm):
    nb = round((mmax - mmin) / dm) + 1
    ms, rs = [], []
    for i in range(nb):
        m = mmin + i * dm
        r = 10.0 ** (a - b * (m - dm / 2.0)) - 10.0 ** (a - b * (m + dm / 2.0))
        ms.append(m)
        rs.append(max(r, 0.0))
    return ms, rs


def _gmm(mag, dist, vs, c, mref, vref):
    dm = mag - mref
    re = math.sqrt(dist * dist + c["c6"] ** 2)
    mu = (
        c["c1"]
        + c["c2"] * dm
        + c["c3"] * dm * dm
        + (c["c4"] + c["c5"] * dm) * math.log(re)
        + c["c7"] * math.log(vs / vref)
    )
    sig = c["c8"] + c["c9"] * mag
    return mu, sig


def _pexc(iml, mu, sig, n):
    eps = (math.log(iml) - mu) / sig
    if eps >= n:
        return 0.0
    return (_phi(n) - _phi(eps)) / _phi(n)


# ──────────────────────────────────────────────────────────────────────
# Reference PSHA computation from multi-format data sources
# ──────────────────────────────────────────────────────────────────────


def compute_reference():
    """Compute full reference hazard curve with corrections applied."""
    # Config from YAML
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)
    slon = config["site"]["lon"]
    slat = config["site"]["lat"]
    vs = config["site"]["vs30"]
    imls = config["imls"]
    nl = config["truncation_level"]

    # GMM from SQLite
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT value FROM metadata WHERE key = 'gmm_Mref'")
    mref = float(cur.fetchone()["value"])
    cur.execute("SELECT value FROM metadata WHERE key = 'gmm_Vref'")
    vref = float(cur.fetchone()["value"])

    cur.execute("SELECT id, weight FROM gmm_tree WHERE weight > 0")
    gmm_entries = cur.fetchall()
    gmm_models = []
    for gm in gmm_entries:
        cur.execute(
            "SELECT param, value FROM gmm_coefficients WHERE model_id = ?",
            (gm["id"],),
        )
        coeffs = {row["param"]: row["value"] for row in cur.fetchall()}
        gmm_models.append({"weight": gm["weight"], "coeffs": coeffs})
    conn.close()

    # Fault sources from GeoJSON
    with open(GEOJSON_PATH) as f:
        geojson = json.load(f)

    seen_geom = set()
    valid_faults = []
    for feat in geojson["features"]:
        props = feat["properties"]
        coords_key = json.dumps(feat["geometry"]["coordinates"], sort_keys=True)
        gk = (coords_key, props["dip"], props["dip_dir"], props["width_km"])
        if gk not in seen_geom:
            seen_geom.add(gk)
            valid_faults.append(feat)

    ni = len(imls)
    hz = [0.0] * ni

    for feat in valid_faults:
        props = feat["properties"]
        trace = [tuple(p) for p in feat["geometry"]["coordinates"]]
        rj = _rjb(slon, slat, trace, props["dip"], props["dip_dir"], props["width_km"])

        mfds = json.loads(props["mfd_json"])
        total_w = sum(m["weight"] for m in mfds)

        for mfd in mfds:
            wb = mfd["weight"] / total_w if total_w > 0 else mfd["weight"]
            if mfd["type"] == "GR":
                ms, rs = _gr_rates(
                    mfd["a"], mfd["b"], mfd["m_min"], mfd["m_max"], mfd["d_mag"]
                )
            else:
                ms, rs = [mfd["m"]], [mfd["rate"]]

            for mag, rate in zip(ms, rs):
                if rate <= 0:
                    continue
                for gm in gmm_models:
                    mu, sig = _gmm(mag, rj, vs, gm["coeffs"], mref, vref)
                    for k in range(ni):
                        hz[k] += wb * gm["weight"] * rate * _pexc(imls[k], mu, sig, nl)

    # Grid seismicity from NetCDF via ncdump
    nc = _nc_vars(
        NC_PATH,
        ["lon", "lat", "depth_km", "a_val", "b_val", "m_min", "m_max", "d_mag"],
    )
    npts = len(nc["lon"])

    for i in range(npts):
        if nc["m_min"][i] > nc["m_max"][i]:
            continue
        if nc["a_val"][i] > 10.0:
            continue
        rh = _rhyp(slon, slat, nc["lon"][i], nc["lat"][i], nc["depth_km"][i])
        ms, rs = _gr_rates(
            nc["a_val"][i],
            nc["b_val"][i],
            nc["m_min"][i],
            nc["m_max"][i],
            nc["d_mag"][i],
        )
        for mag, rate in zip(ms, rs):
            if rate <= 0:
                continue
            for gm in gmm_models:
                mu, sig = _gmm(mag, rh, vs, gm["coeffs"], mref, vref)
                for k in range(ni):
                    hz[k] += gm["weight"] * rate * _pexc(imls[k], mu, sig, nl)

    return imls, hz


def read_agent_output():
    """Read the agent's output CSV."""
    imls, rates = [], []
    with open(OUTPUT_CSV) as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if len(row) < 2:
                continue
            imls.append(float(row[0]))
            rates.append(float(row[1]))
    return imls, rates


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


class TestOutputExists:
    def test_csv_file_exists(self):
        assert os.path.isfile(OUTPUT_CSV), f"Output file {OUTPUT_CSV} does not exist"

    def test_report_file_exists(self):
        assert os.path.isfile(REPORT_FILE), (
            f"Validation report {REPORT_FILE} does not exist"
        )


class TestOutputFormat:
    @pytest.fixture(autouse=True)
    def _load(self):
        if not os.path.isfile(OUTPUT_CSV):
            pytest.skip("Output file missing")

    def test_header_present(self):
        with open(OUTPUT_CSV) as f:
            header = f.readline().strip().lower()
        assert "iml" in header, "Header must contain 'iml'"
        assert "rate" in header or "annual" in header, (
            "Header must contain 'rate' or 'annual'"
        )

    def test_row_count(self):
        imls, rates = read_agent_output()
        assert len(imls) == 20, f"Expected 20 IML rows, got {len(imls)}"
        assert len(rates) == 20, f"Expected 20 rate rows, got {len(rates)}"

    def test_imls_match_config(self):
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f)
        expected_imls = config["imls"]
        agent_imls, _ = read_agent_output()
        for i, (e, a) in enumerate(zip(expected_imls, agent_imls)):
            assert abs(a - e) < 1e-6, (
                f"IML mismatch at index {i}: expected {e}, got {a}"
            )


class TestHazardProperties:
    @pytest.fixture(autouse=True)
    def _load(self):
        if not os.path.isfile(OUTPUT_CSV):
            pytest.skip("Output file missing")
        self.imls, self.rates = read_agent_output()

    def test_rates_positive(self):
        for i, r in enumerate(self.rates):
            assert r >= 0.0, f"Negative rate at IML index {i}: {r}"

    def test_monotonically_decreasing(self):
        for i in range(len(self.rates) - 1):
            assert self.rates[i] >= self.rates[i + 1] - 1e-15, (
                f"Rate not decreasing at index {i}: "
                f"{self.rates[i]} vs {self.rates[i + 1]}"
            )

    def test_first_iml_rate_reasonable(self):
        assert self.rates[0] > 1e-4, (
            f"Rate at smallest IML too small: {self.rates[0]}"
        )

    def test_last_iml_rate_small(self):
        assert self.rates[-1] < 1e-3, (
            f"Rate at largest IML too large: {self.rates[-1]}"
        )


class TestHazardValues:
    """Compare agent output against the independent reference implementation."""

    @pytest.fixture(autouse=True)
    def _load(self):
        if not os.path.isfile(OUTPUT_CSV):
            pytest.skip("Output file missing")
        self.ref_imls, self.ref_rates = compute_reference()
        self.agent_imls, self.agent_rates = read_agent_output()

    def test_all_iml_values(self):
        """Check each IML point against reference within 2% relative tolerance."""
        mismatches = []
        for i in range(len(self.ref_imls)):
            ref = self.ref_rates[i]
            agent = self.agent_rates[i]
            if ref > 1e-8:
                rel_err = abs(agent - ref) / ref
                if rel_err > 0.02:
                    mismatches.append(
                        f"  IML={self.ref_imls[i]}: ref={ref:.6e}, "
                        f"agent={agent:.6e}, rel_err={rel_err:.4f}"
                    )
            else:
                if abs(agent - ref) > 1e-9:
                    mismatches.append(
                        f"  IML={self.ref_imls[i]}: ref={ref:.6e}, "
                        f"agent={agent:.6e}, abs_diff={abs(agent - ref):.6e}"
                    )
        assert len(mismatches) == 0, (
            f"Hazard curve mismatches at {len(mismatches)} IMLs:\n"
            + "\n".join(mismatches)
        )

    def test_mid_range_accuracy(self):
        """Spot-check at IML index 5 (should be ~0.1 g)."""
        idx = 5
        ref = self.ref_rates[idx]
        agent = self.agent_rates[idx]
        assert ref > 1e-5, f"Reference rate at index 5 unexpectedly small: {ref}"
        rel_err = abs(agent - ref) / ref
        assert rel_err < 0.02, (
            f"IML index 5 mismatch: ref={ref:.6e}, agent={agent:.6e}, "
            f"rel_err={rel_err:.4f}"
        )

    def test_high_iml_accuracy(self):
        """Spot-check at IML index 13 (should be ~1.0 g)."""
        idx = 13
        ref = self.ref_rates[idx]
        agent = self.agent_rates[idx]
        if ref > 1e-8:
            rel_err = abs(agent - ref) / ref
            assert rel_err < 0.02, (
                f"IML index 13 mismatch: ref={ref:.6e}, agent={agent:.6e}, "
                f"rel_err={rel_err:.4f}"
            )


class TestValidationReport:
    """Verify the validation report identifies key data quality issues."""

    @pytest.fixture(autouse=True)
    def _load(self):
        if not os.path.isfile(REPORT_FILE):
            pytest.skip("Validation report missing")
        with open(REPORT_FILE) as f:
            self.report = f.read().lower()

    def test_report_not_empty(self):
        assert len(self.report.strip()) > 0, "Validation report is empty"

    def test_mentions_duplicate(self):
        assert "duplicate" in self.report or "redundant" in self.report, (
            "Validation report should identify duplicate fault sources"
        )

    def test_mentions_invalid_or_excluded(self):
        has_kw = any(
            kw in self.report
            for kw in [
                "invalid",
                "excluded",
                "removed",
                "skipped",
                "m_min",
                "mmin",
                "unreasonable",
                "erroneous",
            ]
        )
        assert has_kw, (
            "Validation report should identify excluded invalid data entries"
        )

    def test_mentions_weight_normalization(self):
        has_kw = any(
            kw in self.report for kw in ["normali", "weight", "sum to", "rescal"]
        )
        assert has_kw, (
            "Validation report should mention MFD weight normalization"
        )
