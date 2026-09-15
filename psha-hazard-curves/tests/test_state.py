"""
PSHA Pipeline Diagnostic — verification tests.

Contains an independent reference PSHA computation and disaggregation,
with comparison tests against the pipeline output in /app/output/.

"""

import csv
import json
import math
import os
import sqlite3

import numpy as np
import pytest
from scipy.stats import norm as sp_norm


# ---------------------------------------------------------------------------
# Reference PSHA computation (independent of the pipeline under test)
# ---------------------------------------------------------------------------

def _load_inputs():
    with open("/app/model/sources.json") as f:
        src = json.load(f)
    with open("/app/model/gmm.json") as f:
        gmm = json.load(f)
    with open("/app/model/site.json") as f:
        site = json.load(f)
    with open("/app/model/config.json") as f:
        cfg = json.load(f)
    return src, gmm, site, cfg


def _gr_rates(mfd):
    a, b = mfd["a"], mfd["b"]
    mn, mx, dm = mfd["mMin"], mfd["mMax"], mfd["dMag"]
    out = []
    m = mn + dm / 2.0
    while m < mx - dm / 2.0 + 1e-6:
        lo = 10.0 ** (a - b * (m - dm / 2.0))
        hi = 10.0 ** (a - b * (m + dm / 2.0))
        out.append((round(m, 2), lo - hi))
        m += dm
    return out


def _get_rates(mfd):
    if mfd["type"] == "GR":
        return _gr_rates(mfd)
    return list(zip(mfd["magnitudes"], mfd["rates"]))


def _geo_dist(lon1, lat1, lon2, lat2, kpd):
    la = (lat1 + lat2) / 2.0
    dx = (lon2 - lon1) * math.cos(math.radians(la)) * kpd
    dy = (lat2 - lat1) * kpd
    return math.sqrt(dx * dx + dy * dy)


def _seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 < 1e-10:
        return math.sqrt((px - ax) ** 2 + (py - ay) ** 2)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.sqrt((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2)


def _poly_dist(px, py, pl):
    return min(
        _seg_dist(px, py, pl[i][0], pl[i][1], pl[i + 1][0], pl[i + 1][1])
        for i in range(len(pl) - 1)
    )


def _sub_trace(tkm, cd, sp, ep):
    pts = []
    for i in range(len(tkm) - 1):
        if cd[i + 1] <= sp or cd[i] >= ep:
            continue
        sl = cd[i + 1] - cd[i]
        if sl < 1e-10:
            continue
        dx = tkm[i + 1][0] - tkm[i][0]
        dy = tkm[i + 1][1] - tkm[i][1]
        cs, ce = max(sp, cd[i]), min(ep, cd[i + 1])
        ts, te = (cs - cd[i]) / sl, (ce - cd[i]) / sl
        if not pts:
            pts.append((tkm[i][0] + ts * dx, tkm[i][1] + ts * dy))
        pts.append((tkm[i][0] + te * dx, tkm[i][1] + te * dy))
    return pts


def _fault_rjb(slon, slat, trace, mag, kpd, fstep):
    tkm = [
        (
            (p["longitude"] - slon) * math.cos(math.radians(slat)) * kpd,
            (p["latitude"] - slat) * kpd,
        )
        for p in trace
    ]
    cd = [0.0]
    for i in range(len(tkm) - 1):
        cd.append(
            cd[-1]
            + math.sqrt(
                (tkm[i + 1][0] - tkm[i][0]) ** 2
                + (tkm[i + 1][1] - tkm[i][1]) ** 2
            )
        )
    fl = cd[-1]
    rl = min(10.0 ** (-2.44 + 0.59 * mag), fl)
    if rl >= fl - 0.01:
        return [(_poly_dist(0.0, 0.0, tkm), 1.0)]
    pos = []
    s = 0.0
    while s <= fl - rl + 1e-6:
        pos.append(s)
        s += fstep
    n = len(pos)
    return [
        (_poly_dist(0.0, 0.0, _sub_trace(tkm, cd, sp, sp + rl)), 1.0 / n)
        for sp in pos
    ]


def _ref_hazard():
    src_d, gmm_d, site_d, cfg = _load_inputs()
    imls = np.array(cfg["imls"])
    tn = cfg["truncation"]["level"]
    kpd = cfg["earth_approximation"]["km_per_degree"]
    fstep = cfg["rupture_scaling"]["floating_step_km"]
    mr = gmm_d["reference_magnitude"]
    vr = gmm_d["reference_vs30"]
    vs = site_d["vs30"]
    slon, slat = site_d["longitude"], site_d["latitude"]
    T = cfg["exposure_years"]

    total = np.zeros(len(imls))
    contribs = {}

    for s in src_d["sources"]:
        sr = np.zeros(len(imls))
        for mag, rate in _get_rates(s["mfd"]):
            if s["type"] == "point":
                rjbs = [(_geo_dist(slon, slat, s["longitude"], s["latitude"], kpd), 1.0)]
            else:
                rjbs = _fault_rjb(slon, slat, s["trace"], mag, kpd, fstep)
            for rjb, rw in rjbs:
                for br in gmm_d["branches"]:
                    c = br["coefficients"]
                    sig = br["sigma"]
                    bw = br["weight"]
                    R = math.sqrt(rjb ** 2 + c["h"] ** 2)
                    dm = mag - mr
                    mu = (
                        c["e1"]
                        + c["e2"] * dm
                        + c["e3"] * dm ** 2
                        + (c["c1"] + c["c2"] * dm) * math.log(R)
                        + c["s"] * math.log(vs / vr)
                    )
                    for i, y in enumerate(imls):
                        z = (math.log(y) - mu) / sig
                        if z < tn:
                            p = (sp_norm.cdf(tn) - sp_norm.cdf(z)) / sp_norm.cdf(tn)
                            sr[i] += rate * p * bw * rw
        contribs[s["name"]] = sr
        total += sr

    return imls, total, contribs, T


# ---------------------------------------------------------------------------
# Reference disaggregation computation
# ---------------------------------------------------------------------------

def _ref_interpolate_iml(imls, rates, target_rate):
    """Log-log interpolation to find IML at target annual rate."""
    for i in range(len(rates) - 1):
        if rates[i] >= target_rate >= rates[i + 1]:
            log_r0 = math.log(rates[i])
            log_r1 = math.log(rates[i + 1])
            log_y0 = math.log(imls[i])
            log_y1 = math.log(imls[i + 1])
            frac = (math.log(target_rate) - log_r0) / (log_r1 - log_r0)
            return math.exp(log_y0 + frac * (log_y1 - log_y0))
    if target_rate >= rates[0]:
        return imls[0]
    return imls[-1]


def _ref_find_bin(value, vmin, vmax, width):
    """Find the bin center for a value within a binning scheme."""
    if value < vmin or value >= vmax:
        return None
    idx = int((value - vmin) / width)
    return round(vmin + (idx + 0.5) * width, 4)


def _ref_disagg():
    """Compute reference disaggregation independently."""
    src_d, gmm_d, site_d, cfg = _load_inputs()
    imls_ref, total_ref, _, _ = _ref_hazard()

    dcfg = cfg["disaggregation"]
    target_rate = 1.0 / dcfg["return_period_years"]
    target_iml = _ref_interpolate_iml(
        list(imls_ref), list(total_ref), target_rate
    )

    bcfg = dcfg["bins"]
    slon, slat = site_d["longitude"], site_d["latitude"]
    vs30 = site_d["vs30"]
    kpd = cfg["earth_approximation"]["km_per_degree"]
    fstep = cfg["rupture_scaling"]["floating_step_km"]
    mref = gmm_d["reference_magnitude"]
    vref = gmm_d["reference_vs30"]
    trunc = cfg["truncation"]["level"]

    bins = {}

    for src in src_d["sources"]:
        for mag, rate in _get_rates(src["mfd"]):
            if src["type"] == "point":
                rjbs = [
                    (_geo_dist(slon, slat, src["longitude"],
                               src["latitude"], kpd), 1.0)
                ]
            else:
                rjbs = _fault_rjb(slon, slat, src["trace"], mag, kpd, fstep)

            for rjb, rw in rjbs:
                for br in gmm_d["branches"]:
                    c = br["coefficients"]
                    sig = br["sigma"]
                    bw = br["weight"]
                    R = math.sqrt(rjb ** 2 + c["h"] ** 2)
                    dm = mag - mref
                    mu = (
                        c["e1"]
                        + c["e2"] * dm
                        + c["e3"] * dm ** 2
                        + (c["c1"] + c["c2"] * dm) * math.log(R)
                        + c["s"] * math.log(vs30 / vref)
                    )

                    eps = (math.log(target_iml) - mu) / sig

                    z = (math.log(target_iml) - mu) / sig
                    if z < trunc:
                        exc = (sp_norm.cdf(trunc) - sp_norm.cdf(z)) / sp_norm.cdf(trunc)
                    else:
                        exc = 0.0

                    contribution = rate * exc * bw * rw

                    mb = _ref_find_bin(mag, bcfg["mag_min"],
                                       bcfg["mag_max"], bcfg["mag_width"])
                    db = _ref_find_bin(rjb, bcfg["dist_min"],
                                       bcfg["dist_max"], bcfg["dist_width"])
                    eb = _ref_find_bin(eps, bcfg["eps_min"],
                                       bcfg["eps_max"], bcfg["eps_width"])

                    if mb is not None and db is not None and eb is not None:
                        key = (mb, db, eb)
                        bins[key] = bins.get(key, 0.0) + contribution

    total = sum(bins.values())
    if total > 0:
        normalized = {k: v / total for k, v in bins.items()}
    else:
        normalized = dict(bins)

    mag_marginal = {}
    dist_marginal = {}
    mean_eps = 0.0
    for (m, d, e), contrib in normalized.items():
        mag_marginal[m] = mag_marginal.get(m, 0.0) + contrib
        dist_marginal[d] = dist_marginal.get(d, 0.0) + contrib
        mean_eps += e * contrib

    modal_mag = max(mag_marginal, key=mag_marginal.get)
    modal_dist = max(dist_marginal, key=dist_marginal.get)

    return {
        "target_iml": target_iml,
        "modal_mag": modal_mag,
        "modal_dist": modal_dist,
        "mean_epsilon": mean_eps,
        "total_rate_at_target": total,
        "bins": normalized,
    }


# ---------------------------------------------------------------------------
# Agent output readers
# ---------------------------------------------------------------------------

def _read_hazard_csv():
    rows = []
    with open("/app/output/hazard_curves.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(
                {
                    "iml": float(row["iml"]),
                    "annual_rate": float(row["annual_rate"]),
                    "poisson_prob_50yr": float(row["poisson_prob_50yr"]),
                }
            )
    return rows


def _read_source_csv():
    contribs = {}
    with open("/app/output/source_contributions.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["source_name"]
            if name not in contribs:
                contribs[name] = []
            contribs[name].append(
                {"iml": float(row["iml"]), "annual_rate": float(row["annual_rate"])}
            )
    return contribs


# ---------------------------------------------------------------------------
# Tests — Hazard Curves
# ---------------------------------------------------------------------------

class TestOutputFilesExist:
    def test_hazard_curves_file(self):
        assert os.path.isfile("/app/output/hazard_curves.csv"), (
            "Missing /app/output/hazard_curves.csv"
        )

    def test_source_contributions_file(self):
        assert os.path.isfile("/app/output/source_contributions.csv"), (
            "Missing /app/output/source_contributions.csv"
        )


class TestHazardCurveFormat:
    def test_header_columns(self):
        with open("/app/output/hazard_curves.csv") as f:
            header = f.readline().strip().split(",")
        assert header == ["iml", "annual_rate", "poisson_prob_50yr"]

    def test_row_count(self):
        rows = _read_hazard_csv()
        assert len(rows) == 14, f"Expected 14 IML rows, got {len(rows)}"

    def test_imls_match_config(self):
        with open("/app/model/config.json") as f:
            cfg = json.load(f)
        rows = _read_hazard_csv()
        for i, row in enumerate(rows):
            assert abs(row["iml"] - cfg["imls"][i]) < 1e-6, (
                f"IML mismatch at index {i}: {row['iml']} vs {cfg['imls'][i]}"
            )


class TestHazardCurveMonotonicity:
    def test_annual_rates_monotonically_decrease(self):
        rows = _read_hazard_csv()
        rates = [r["annual_rate"] for r in rows]
        for i in range(len(rates) - 1):
            assert rates[i] >= rates[i + 1] - 1e-15, (
                f"Non-monotonic at IML index {i}: {rates[i]:.6e} < {rates[i+1]:.6e}"
            )


class TestHazardCurveValues:
    @pytest.fixture(scope="class")
    def ref(self):
        return _ref_hazard()

    def test_total_hazard_curve(self, ref):
        imls_ref, total_ref, _, _ = ref
        rows = _read_hazard_csv()
        for i, row in enumerate(rows):
            agent_rate = row["annual_rate"]
            expected = total_ref[i]
            if expected > 1e-12:
                rel = abs(agent_rate - expected) / expected
                assert rel < 0.02, (
                    f"IML={imls_ref[i]}: expected {expected:.8e}, "
                    f"got {agent_rate:.8e}, rel_err={rel:.4f}"
                )
            else:
                assert abs(agent_rate - expected) < 1e-12, (
                    f"IML={imls_ref[i]}: expected ~0, got {agent_rate:.8e}"
                )


class TestPoissonConversion:
    @pytest.fixture(scope="class")
    def ref(self):
        return _ref_hazard()

    def test_poisson_consistent_with_rate(self, ref):
        _, _, _, T = ref
        rows = _read_hazard_csv()
        for row in rows:
            rate = row["annual_rate"]
            pp = row["poisson_prob_50yr"]
            expected_pp = 1.0 - math.exp(-rate * T)
            if expected_pp > 1e-12:
                rel = abs(pp - expected_pp) / expected_pp
                assert rel < 0.001, (
                    f"Poisson mismatch at IML={row['iml']}: "
                    f"expected {expected_pp:.8e}, got {pp:.8e}"
                )
            else:
                assert abs(pp - expected_pp) < 1e-12


class TestSourceContributions:
    @pytest.fixture(scope="class")
    def ref(self):
        return _ref_hazard()

    def test_all_sources_present(self, ref):
        _, _, contribs_ref, _ = ref
        agent_c = _read_source_csv()
        for name in contribs_ref:
            assert name in agent_c, f"Missing source contribution: {name}"

    def test_contributions_sum_to_total(self, ref):
        imls_ref, _, _, _ = ref
        rows = _read_hazard_csv()
        agent_c = _read_source_csv()
        for i in range(len(imls_ref)):
            total_agent = rows[i]["annual_rate"]
            contrib_sum = sum(
                agent_c[name][i]["annual_rate"] for name in agent_c
            )
            if total_agent > 1e-12:
                rel = abs(contrib_sum - total_agent) / total_agent
                assert rel < 0.01, (
                    f"Contribution sum mismatch at IML={imls_ref[i]}: "
                    f"sum={contrib_sum:.8e}, total={total_agent:.8e}"
                )
            else:
                assert abs(contrib_sum - total_agent) < 1e-12

    def test_source_contribution_values(self, ref):
        imls_ref, _, contribs_ref, _ = ref
        agent_c = _read_source_csv()
        for name in contribs_ref:
            if name not in agent_c:
                continue
            for i in range(len(imls_ref)):
                expected = contribs_ref[name][i]
                actual = agent_c[name][i]["annual_rate"]
                if expected > 1e-10:
                    rel = abs(actual - expected) / expected
                    assert rel < 0.05, (
                        f"Source {name} IML={imls_ref[i]}: "
                        f"expected {expected:.8e}, got {actual:.8e}, "
                        f"rel_err={rel:.4f}"
                    )


class TestPhysicalBounds:
    def test_rates_non_negative(self):
        rows = _read_hazard_csv()
        for row in rows:
            assert row["annual_rate"] >= -1e-15, (
                f"Negative rate at IML={row['iml']}"
            )

    def test_poisson_in_unit_interval(self):
        rows = _read_hazard_csv()
        for row in rows:
            assert -1e-15 <= row["poisson_prob_50yr"] <= 1.0 + 1e-15, (
                f"Poisson out of [0,1] at IML={row['iml']}"
            )

    def test_highest_iml_near_zero(self):
        rows = _read_hazard_csv()
        last = rows[-1]
        assert last["annual_rate"] < 0.01, (
            f"Rate at IML={last['iml']} unexpectedly large: {last['annual_rate']:.6e}"
        )

    def test_lowest_iml_significant(self):
        rows = _read_hazard_csv()
        first = rows[0]
        assert first["annual_rate"] > 0.01, (
            f"Rate at IML={first['iml']} unexpectedly small: {first['annual_rate']:.6e}"
        )


# ---------------------------------------------------------------------------
# Tests — Disaggregation Output Files
# ---------------------------------------------------------------------------

class TestDisaggOutputExists:
    def test_disagg_db_exists(self):
        assert os.path.isfile("/app/output/disagg.db"), (
            "Missing /app/output/disagg.db"
        )

    def test_disagg_summary_exists(self):
        assert os.path.isfile("/app/output/disagg_summary.json"), (
            "Missing /app/output/disagg_summary.json"
        )


# ---------------------------------------------------------------------------
# Tests — Disaggregation Database Schema and Integrity
# ---------------------------------------------------------------------------

class TestDisaggDatabase:
    def test_table_exists(self):
        conn = sqlite3.connect("/app/output/disagg.db")
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='bins'"
        )
        row = cur.fetchone()
        conn.close()
        assert row is not None, "Table 'bins' not found in disagg.db"

    def test_table_columns(self):
        conn = sqlite3.connect("/app/output/disagg.db")
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(bins)")
        cols = {row[1] for row in cur.fetchall()}
        conn.close()
        for c in ("mag_center", "dist_center", "eps_center", "contribution"):
            assert c in cols, f"Missing column '{c}' in bins table"

    def test_bins_sum_to_one(self):
        conn = sqlite3.connect("/app/output/disagg.db")
        cur = conn.cursor()
        cur.execute("SELECT SUM(contribution) FROM bins")
        total = cur.fetchone()[0]
        conn.close()
        assert total is not None, "No data in bins table"
        assert abs(total - 1.0) < 0.01, (
            f"Bins sum to {total:.6f}, expected ~1.0"
        )

    def test_contributions_non_negative(self):
        conn = sqlite3.connect("/app/output/disagg.db")
        cur = conn.cursor()
        cur.execute("SELECT MIN(contribution) FROM bins")
        min_val = cur.fetchone()[0]
        conn.close()
        assert min_val is not None and min_val >= -1e-15, (
            f"Negative contribution found: {min_val}"
        )

    def test_has_multiple_bins(self):
        conn = sqlite3.connect("/app/output/disagg.db")
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM bins WHERE contribution > 1e-10")
        count = cur.fetchone()[0]
        conn.close()
        assert count > 5, f"Expected >5 significant bins, got {count}"

    def test_mag_within_range(self):
        conn = sqlite3.connect("/app/output/disagg.db")
        cur = conn.cursor()
        cur.execute("SELECT MIN(mag_center), MAX(mag_center) FROM bins")
        lo, hi = cur.fetchone()
        conn.close()
        assert lo >= 5.0 and hi <= 8.0, (
            f"mag_center out of [5,8]: min={lo}, max={hi}"
        )

    def test_dist_within_range(self):
        conn = sqlite3.connect("/app/output/disagg.db")
        cur = conn.cursor()
        cur.execute("SELECT MIN(dist_center), MAX(dist_center) FROM bins")
        lo, hi = cur.fetchone()
        conn.close()
        assert lo >= 0.0 and hi <= 200.0, (
            f"dist_center out of [0,200]: min={lo}, max={hi}"
        )


# ---------------------------------------------------------------------------
# Tests — Disaggregation Summary Values
# ---------------------------------------------------------------------------

class TestDisaggSummary:
    @pytest.fixture(scope="class")
    def summary(self):
        with open("/app/output/disagg_summary.json") as f:
            return json.load(f)

    @pytest.fixture(scope="class")
    def ref_d(self):
        return _ref_disagg()

    def test_required_keys(self, summary):
        for key in ("target_iml", "modal_mag", "modal_dist",
                     "mean_epsilon", "total_rate_at_target"):
            assert key in summary, (
                f"Missing key in disagg_summary.json: {key}"
            )

    def test_target_iml(self, summary, ref_d):
        expected = ref_d["target_iml"]
        actual = summary["target_iml"]
        rel = abs(actual - expected) / expected
        assert rel < 0.05, (
            f"target_iml: expected {expected:.6f}, "
            f"got {actual:.6f}, rel_err={rel:.4f}"
        )

    def test_modal_magnitude(self, summary, ref_d):
        assert abs(summary["modal_mag"] - ref_d["modal_mag"]) < 0.01, (
            f"modal_mag: expected {ref_d['modal_mag']}, "
            f"got {summary['modal_mag']}"
        )

    def test_modal_distance(self, summary, ref_d):
        assert abs(summary["modal_dist"] - ref_d["modal_dist"]) < 0.01, (
            f"modal_dist: expected {ref_d['modal_dist']}, "
            f"got {summary['modal_dist']}"
        )

    def test_mean_epsilon(self, summary, ref_d):
        expected = ref_d["mean_epsilon"]
        actual = summary["mean_epsilon"]
        assert abs(actual - expected) < 0.2, (
            f"mean_epsilon: expected {expected:.4f}, got {actual:.4f}"
        )

    def test_total_rate(self, summary, ref_d):
        expected = ref_d["total_rate_at_target"]
        actual = summary["total_rate_at_target"]
        if expected > 1e-12:
            rel = abs(actual - expected) / expected
            assert rel < 0.10, (
                f"total_rate_at_target: expected {expected:.6e}, "
                f"got {actual:.6e}, rel_err={rel:.4f}"
            )


# ---------------------------------------------------------------------------
# Tests — Disaggregation Bin Accuracy
# ---------------------------------------------------------------------------

class TestDisaggBinValues:
    @pytest.fixture(scope="class")
    def ref_d(self):
        return _ref_disagg()

    def test_top_bins_match(self, ref_d):
        """Verify the highest-contributing bins match the reference."""
        ref_bins = ref_d["bins"]
        sorted_ref = sorted(ref_bins.items(), key=lambda x: x[1],
                            reverse=True)

        conn = sqlite3.connect("/app/output/disagg.db")
        cur = conn.cursor()

        checked = 0
        for (m, d, e), expected_c in sorted_ref:
            if expected_c < 0.005:
                break
            cur.execute(
                "SELECT contribution FROM bins WHERE "
                "abs(mag_center - ?) < 0.01 AND "
                "abs(dist_center - ?) < 0.01 AND "
                "abs(eps_center - ?) < 0.01",
                (m, d, e),
            )
            row = cur.fetchone()
            assert row is not None, (
                f"Missing bin (m={m}, d={d}, eps={e}) in database"
            )
            actual_c = row[0]
            rel = abs(actual_c - expected_c) / expected_c
            assert rel < 0.10, (
                f"Bin (m={m}, d={d}, eps={e}): "
                f"expected {expected_c:.6f}, got {actual_c:.6f}, "
                f"rel_err={rel:.4f}"
            )
            checked += 1

        conn.close()
        assert checked >= 3, (
            f"Only {checked} significant bins found in reference"
        )

    def test_marginal_mag_distribution(self, ref_d):
        """Verify the marginal magnitude distribution."""
        ref_bins = ref_d["bins"]
        ref_mag = {}
        for (m, d, e), c in ref_bins.items():
            ref_mag[m] = ref_mag.get(m, 0.0) + c

        conn = sqlite3.connect("/app/output/disagg.db")
        cur = conn.cursor()

        for m, expected in ref_mag.items():
            if expected < 0.01:
                continue
            cur.execute(
                "SELECT SUM(contribution) FROM bins "
                "WHERE abs(mag_center - ?) < 0.01",
                (m,),
            )
            row = cur.fetchone()
            actual = row[0] if row[0] is not None else 0.0
            rel = abs(actual - expected) / expected
            assert rel < 0.10, (
                f"Marginal mag={m}: expected {expected:.4f}, "
                f"got {actual:.4f}, rel_err={rel:.4f}"
            )

        conn.close()


# ---------------------------------------------------------------------------
# Tests — Post-Processing Outputs (gnuplot, sqlite3, jq)
# ---------------------------------------------------------------------------

class TestPostProcessingOutputs:
    def test_hazard_curve_png_exists(self):
        assert os.path.isfile("/app/output/hazard_curve.png"), (
            "Missing /app/output/hazard_curve.png"
        )

    def test_hazard_curve_png_valid(self):
        with open("/app/output/hazard_curve.png", "rb") as f:
            header = f.read(8)
        assert header[:4] == b'\x89PNG', (
            "hazard_curve.png is not a valid PNG file "
            f"(magic bytes: {header[:4].hex()})"
        )

    def test_marginal_mag_csv_exists(self):
        assert os.path.isfile("/app/output/marginal_mag.csv"), (
            "Missing /app/output/marginal_mag.csv"
        )

    def test_marginal_dist_csv_exists(self):
        assert os.path.isfile("/app/output/marginal_dist.csv"), (
            "Missing /app/output/marginal_dist.csv"
        )

    def test_disagg_report_json_exists(self):
        assert os.path.isfile("/app/output/disagg_report.json"), (
            "Missing /app/output/disagg_report.json"
        )


class TestMarginalDistributions:
    @pytest.fixture(scope="class")
    def ref_d(self):
        return _ref_disagg()

    def test_marginal_mag_values(self, ref_d):
        """Marginal magnitude distribution matches reference sums."""
        ref_bins = ref_d["bins"]
        ref_mag = {}
        for (m, d, e), c in ref_bins.items():
            ref_mag[m] = ref_mag.get(m, 0.0) + c

        agent_mag = {}
        with open("/app/output/marginal_mag.csv") as f:
            reader = csv.DictReader(f)
            for row in reader:
                agent_mag[float(row["mag_center"])] = float(row["marginal"])

        for m, expected in ref_mag.items():
            if expected < 0.01:
                continue
            matched = None
            for am in agent_mag:
                if abs(am - m) < 0.01:
                    matched = am
                    break
            assert matched is not None, (
                f"Missing mag bin {m} in marginal_mag.csv"
            )
            actual = agent_mag[matched]
            rel = abs(actual - expected) / expected
            assert rel < 0.10, (
                f"Marginal mag={m}: expected {expected:.4f}, "
                f"got {actual:.4f}, rel_err={rel:.4f}"
            )

    def test_marginal_mag_sums_to_one(self):
        total = 0.0
        with open("/app/output/marginal_mag.csv") as f:
            reader = csv.DictReader(f)
            for row in reader:
                total += float(row["marginal"])
        assert abs(total - 1.0) < 0.02, (
            f"Marginal magnitude sums to {total:.4f}, expected ~1.0"
        )

    def test_marginal_dist_values(self, ref_d):
        """Marginal distance distribution matches reference sums."""
        ref_bins = ref_d["bins"]
        ref_dist = {}
        for (m, d, e), c in ref_bins.items():
            ref_dist[d] = ref_dist.get(d, 0.0) + c

        agent_dist = {}
        with open("/app/output/marginal_dist.csv") as f:
            reader = csv.DictReader(f)
            for row in reader:
                agent_dist[float(row["dist_center"])] = float(row["marginal"])

        for d, expected in ref_dist.items():
            if expected < 0.01:
                continue
            matched = None
            for ad in agent_dist:
                if abs(ad - d) < 0.01:
                    matched = ad
                    break
            assert matched is not None, (
                f"Missing dist bin {d} in marginal_dist.csv"
            )
            actual = agent_dist[matched]
            rel = abs(actual - expected) / expected
            assert rel < 0.10, (
                f"Marginal dist={d}: expected {expected:.4f}, "
                f"got {actual:.4f}, rel_err={rel:.4f}"
            )

    def test_marginal_dist_sums_to_one(self):
        total = 0.0
        with open("/app/output/marginal_dist.csv") as f:
            reader = csv.DictReader(f)
            for row in reader:
                total += float(row["marginal"])
        assert abs(total - 1.0) < 0.02, (
            f"Marginal distance sums to {total:.4f}, expected ~1.0"
        )


# ---------------------------------------------------------------------------
# Tests — Disaggregation Report (jq-generated)
# ---------------------------------------------------------------------------

class TestDisaggReport:
    @pytest.fixture(scope="class")
    def report(self):
        with open("/app/output/disagg_report.json") as f:
            return json.load(f)

    @pytest.fixture(scope="class")
    def ref_d(self):
        return _ref_disagg()

    def test_required_sections(self, report):
        for section in ("report_type", "site", "analysis", "disaggregation"):
            assert section in report, (
                f"Missing section '{section}' in disagg_report.json"
            )

    def test_site_longitude(self, report):
        with open("/app/model/site.json") as f:
            site = json.load(f)
        actual = report["site"]["longitude"]
        assert actual is not None, "site.longitude is null in report"
        assert abs(actual - site["longitude"]) < 0.01, (
            f"site.longitude: expected {site['longitude']}, got {actual}"
        )

    def test_site_latitude(self, report):
        with open("/app/model/site.json") as f:
            site = json.load(f)
        actual = report["site"]["latitude"]
        assert actual is not None, "site.latitude is null in report"
        assert abs(actual - site["latitude"]) < 0.01, (
            f"site.latitude: expected {site['latitude']}, got {actual}"
        )

    def test_site_vs30(self, report):
        with open("/app/model/site.json") as f:
            site = json.load(f)
        actual = report["site"]["vs30_m_s"]
        assert actual is not None, "site.vs30_m_s is null in report"
        assert abs(actual - site["vs30"]) < 0.1, (
            f"site.vs30: expected {site['vs30']}, got {actual}"
        )

    def test_return_period(self, report):
        with open("/app/model/config.json") as f:
            cfg = json.load(f)
        actual = report["analysis"]["return_period_years"]
        expected = cfg["disaggregation"]["return_period_years"]
        assert actual is not None, "analysis.return_period_years is null"
        assert actual == expected, (
            f"return_period_years: expected {expected}, got {actual}"
        )

    def test_exposure_years(self, report):
        with open("/app/model/config.json") as f:
            cfg = json.load(f)
        actual = report["analysis"]["exposure_years"]
        expected = cfg["exposure_years"]
        assert actual is not None, "analysis.exposure_years is null"
        assert actual == expected, (
            f"exposure_years: expected {expected}, got {actual}"
        )

    def test_disagg_target_iml(self, report, ref_d):
        expected = ref_d["target_iml"]
        actual = report["disaggregation"]["target_iml_g"]
        assert actual is not None, "target_iml_g is null in report"
        rel = abs(actual - expected) / expected
        assert rel < 0.05, (
            f"target_iml in report: expected {expected:.6f}, "
            f"got {actual:.6f}, rel_err={rel:.4f}"
        )

    def test_disagg_modal_magnitude(self, report, ref_d):
        actual = report["disaggregation"]["modal_magnitude"]
        expected = ref_d["modal_mag"]
        assert actual is not None, "modal_magnitude is null in report"
        assert abs(actual - expected) < 0.01, (
            f"modal_magnitude: expected {expected}, got {actual}"
        )

    def test_disagg_modal_distance(self, report, ref_d):
        actual = report["disaggregation"]["modal_distance_km"]
        expected = ref_d["modal_dist"]
        assert actual is not None, "modal_distance_km is null in report"
        assert abs(actual - expected) < 0.01, (
            f"modal_distance_km: expected {expected}, got {actual}"
        )
