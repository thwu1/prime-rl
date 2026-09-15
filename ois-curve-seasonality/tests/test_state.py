#!/usr/bin/env python3
"""
Property-based tests for OIS multi-curve framework with seasonality.

"""

import json
import math
import os
import re
import sqlite3
import calendar as cal_mod
from datetime import date, timedelta

import pytest
import yaml

# ────────────────────── helpers ──────────────────────

def load(path):
    with open(path) as f:
        return json.load(f)

def pd(s):
    return date.fromisoformat(s)

def is_bd(d, hols):
    return d.weekday() < 5 and d not in hols

def next_bd(d, hols):
    d += timedelta(days=1)
    while not is_bd(d, hols):
        d += timedelta(days=1)
    return d

def prev_bd(d, hols):
    d -= timedelta(days=1)
    while not is_bd(d, hols):
        d -= timedelta(days=1)
    return d

def mod_fol(d, hols):
    if is_bd(d, hols):
        return d
    orig_m = d.month
    nxt = d
    while not is_bd(nxt, hols):
        nxt += timedelta(days=1)
    if nxt.month != orig_m:
        prv = d
        while not is_bd(prv, hols):
            prv -= timedelta(days=1)
        return prv
    return nxt

def add_months(d, months):
    total = d.month + months
    y = d.year + (total - 1) // 12
    m = (total - 1) % 12 + 1
    mx = cal_mod.monthrange(y, m)[1]
    return date(y, m, min(d.day, mx))

def dcf(d1, d2):
    return (d2 - d1).days / 360.0

def gen_pdates(eff, mat, freq, hols):
    dates = []
    n = 1
    while True:
        raw = add_months(eff, freq * n)
        if raw >= mat:
            adj = mod_fol(mat, hols)
            if not dates or dates[-1] != adj:
                dates.append(adj)
            break
        dates.append(mod_fol(raw, hols))
        n += 1
    return dates

def classify_bd(d, hols):
    y, m = d.year, d.month
    mx = cal_mod.monthrange(y, m)[1]
    lbd = date(y, m, mx)
    while not is_bd(lbd, hols):
        lbd -= timedelta(days=1)
    if d == lbd:
        return "month_end"
    fbd = date(y, m, 1)
    while not is_bd(fbd, hols):
        fbd += timedelta(days=1)
    if d == fbd:
        return "first_bd"
    sbd = next_bd(fbd, hols)
    if d == sbd:
        return "second_bd"
    slbd = prev_bd(lbd, hols)
    if d == slbd:
        return "second_last_bd"
    fif = date(y, m, 15)
    while not is_bd(fif, hols):
        fif += timedelta(days=1)
    if fif.month == m and d == fif:
        return "fifteenth"
    return "other"

# ────────────────────── fixtures ──────────────────────

@pytest.fixture(scope="module")
def results():
    return load("/app/output/results.json")

@pytest.fixture(scope="module")
def market():
    data = load("/app/data/market_data.json")
    return {
        "valuation_date": data["valuation_date"],
        "ois_quotes": data["ois_quotes"],
        "node_dates": data["node_dates"],
    }

@pytest.fixture(scope="module")
def holidays():
    data = load("/app/data/holidays.json")
    return set(pd(d) for d in data["us_holidays"])

@pytest.fixture(scope="module")
def portfolio():
    with open("/app/data/portfolio.yaml") as f:
        return yaml.safe_load(f)

# ────────────────────── test 1: output structure ──────────────────────

def test_output_structure(results, market, portfolio):
    """Results file contains all required top-level keys with correct types."""
    for key in ["discount_factors", "forward_overnight_rates", "swap_pvs", "bucketed_pv01"]:
        assert key in results, f"Missing key: {key}"
    assert isinstance(results["discount_factors"], dict)
    assert isinstance(results["forward_overnight_rates"], dict)
    assert isinstance(results["swap_pvs"], dict)
    assert isinstance(results["bucketed_pv01"], dict)

    for nd in market["node_dates"]:
        assert nd in results["discount_factors"], f"Missing DF for node {nd}"

    for sw in portfolio["swaps"]:
        assert sw["id"] in results["swap_pvs"], f"Missing PV for {sw['id']}"
        assert sw["id"] in results["bucketed_pv01"], f"Missing PV01 for {sw['id']}"

def test_pv01_keys(results, market):
    """Each PV01 entry has one value per OIS quote label."""
    labels = {q["label"] for q in market["ois_quotes"]}
    for sid, pv01 in results["bucketed_pv01"].items():
        assert set(pv01.keys()) == labels, f"PV01 labels mismatch for {sid}"

# ────────────────────── test 2: DF properties ──────────────────────

def test_discount_factor_range(results, market):
    """All DFs are in (0, 1) and monotonically decrease with date."""
    val_date = pd(market["valuation_date"])
    entries = sorted(results["discount_factors"].items(), key=lambda x: x[0])
    prev_d = val_date
    prev_df = 1.0
    for d_str, df_val in entries:
        d = pd(d_str)
        assert 0 < df_val < 1, f"DF out of range at {d_str}: {df_val}"
        assert d > prev_d, "Node dates not sorted"
        assert df_val < prev_df, f"DF not decreasing: {prev_df} -> {df_val} at {d_str}"
        prev_d = d
        prev_df = df_val

# ────────────────────── test 3: repricing ──────────────────────

def test_repricing(results, market, holidays):
    """
    Calibrated curve must reprice all input OIS swap quotes within 0.01 bps.
    Reconstructs DFs from the output forward overnight rates.
    """
    val_date = pd(market["valuation_date"])
    fwds = results["forward_overnight_rates"]

    bd_dates = sorted(pd(d) for d in fwds.keys())
    df_map = {val_date: 1.0}

    for i, bd in enumerate(bd_dates):
        r = fwds[bd.isoformat()]
        if i + 1 < len(bd_dates):
            nxt = bd_dates[i + 1]
        else:
            nxt = bd + timedelta(days=1)
            while not is_bd(nxt, holidays):
                nxt += timedelta(days=1)
        dc = dcf(bd, nxt)
        df_map[nxt] = df_map[bd] / (1 + r * dc)

    eff = val_date
    for _ in range(2):
        eff = next_bd(eff, holidays)

    for q in market["ois_quotes"]:
        tm = q["tenor_months"]
        rate_in = q["rate"]
        mat = mod_fol(add_months(eff, tm), holidays)
        freq = 12 if tm <= 12 else 6
        pdates = gen_pdates(eff, mat, freq, holidays)

        ann = 0.0
        prev = eff
        for p in pdates:
            assert p in df_map, f"Payment date {p} not in DF map for {q['label']}"
            ann += dcf(prev, p) * df_map[p]
            prev = p

        assert eff in df_map, f"Effective {eff} not in DF map"
        assert mat in df_map, f"Maturity {mat} not in DF map for {q['label']}"

        implied = (df_map[eff] - df_map[mat]) / ann
        err = abs(implied - rate_in)
        assert err < 1e-6, (
            f"Repricing failed for {q['label']}: implied={implied:.8f}, "
            f"input={rate_in:.8f}, error={err:.2e}"
        )

# ────────────────────── test 4: seasonality in forward rates ──────────────────────

def test_seasonality_month_end(results, market, holidays):
    """
    Forward rates on month-end dates should be systematically higher than
    neighbouring 'other' dates, confirming the curve captures intra-month seasonality.
    """
    fwds = results["forward_overnight_rates"]
    nodes = sorted(pd(d) for d in market["node_dates"])

    test_months = [
        (2024, 8), (2024, 10), (2024, 11), (2025, 1), (2025, 3),
    ]

    checks_passed = 0
    for y, m in test_months:
        mx = cal_mod.monthrange(y, m)[1]
        lbd = date(y, m, mx)
        while not is_bd(lbd, holidays):
            lbd -= timedelta(days=1)

        nearby = prev_bd(lbd, holidays)
        cat_nearby = classify_bd(nearby, holidays)
        if cat_nearby == "second_last_bd":
            nearby = prev_bd(nearby, holidays)
            cat_nearby = classify_bd(nearby, holidays)

        if cat_nearby != "other":
            continue

        lbd_str = lbd.isoformat()
        nearby_str = nearby.isoformat()
        if lbd_str not in fwds or nearby_str not in fwds:
            continue

        in_same_interval = True
        for k in range(len(nodes) - 1):
            if nodes[k] < lbd <= nodes[k + 1] and nodes[k] < nearby <= nodes[k + 1]:
                break
            if (nodes[k] < lbd <= nodes[k + 1]) != (nodes[k] < nearby <= nodes[k + 1]):
                in_same_interval = False
                break
        if not in_same_interval:
            continue

        diff = fwds[lbd_str] - fwds[nearby_str]
        assert diff > 0.0005, (
            f"Month-end seasonality too weak at {lbd_str}: diff={diff:.6f}, "
            f"expected > 5 bps"
        )
        assert diff < 0.003, (
            f"Month-end seasonality implausibly strong at {lbd_str}: diff={diff:.6f}"
        )
        checks_passed += 1

    assert checks_passed >= 3, f"Only {checks_passed} seasonality checks passed (need >= 3)"

# ────────────────────── test 5: swap PV signs ──────────────────────

def test_swap_pv_signs(results, market, portfolio):
    """Swap PV signs are consistent with fixed rate vs. market par rate."""
    par_rates = {q["label"]: q["rate"] for q in market["ois_quotes"]}
    tenor_to_label = {q["tenor_months"]: q["label"] for q in market["ois_quotes"]}

    for sw in portfolio["swaps"]:
        sid = sw["id"]
        fixed_r = sw["fixed_rate"]
        tenor = sw["tenor_months"]
        direction = sw["direction"]
        pv = results["swap_pvs"][sid]

        if tenor in tenor_to_label:
            par = par_rates[tenor_to_label[tenor]]
        else:
            labels_sorted = sorted(tenor_to_label.keys())
            lower = max(t for t in labels_sorted if t <= tenor)
            upper = min(t for t in labels_sorted if t >= tenor)
            if lower == upper:
                par = par_rates[tenor_to_label[lower]]
            else:
                alpha = (tenor - lower) / (upper - lower)
                par = par_rates[tenor_to_label[lower]] * (1 - alpha) + par_rates[tenor_to_label[upper]] * alpha

        if direction == "receiver":
            if fixed_r > par + 0.001:
                assert pv > 0, f"{sid}: receiver fixed={fixed_r} > par ~{par} should have PV>0, got {pv}"
            elif fixed_r < par - 0.001:
                assert pv < 0, f"{sid}: receiver fixed={fixed_r} < par ~{par} should have PV<0, got {pv}"
        else:
            if fixed_r > par + 0.001:
                assert pv < 0, f"{sid}: payer fixed={fixed_r} > par ~{par} should have PV<0, got {pv}"
            elif fixed_r < par - 0.001:
                assert pv > 0, f"{sid}: payer fixed={fixed_r} < par ~{par} should have PV>0, got {pv}"

# ────────────────────── test 6: PV01 properties ──────────────────────

def test_pv01_signs(results, market, portfolio):
    """PV01 signs: receiver < 0, payer > 0. Dominant bucket near swap tenor."""
    tenor_labels = {q["tenor_months"]: q["label"] for q in market["ois_quotes"]}

    for sw in portfolio["swaps"]:
        sid = sw["id"]
        direction = sw["direction"]
        tenor = sw["tenor_months"]
        pv01 = results["bucketed_pv01"][sid]

        total_pv01 = sum(pv01.values())
        if direction == "receiver":
            assert total_pv01 < 0, f"{sid}: receiver total PV01 should be < 0, got {total_pv01}"
        else:
            assert total_pv01 > 0, f"{sid}: payer total PV01 should be > 0, got {total_pv01}"

        if tenor in tenor_labels:
            key_bucket = tenor_labels[tenor]
            key_val = abs(pv01[key_bucket])
            max_val = max(abs(v) for v in pv01.values())
            assert key_val > max_val * 0.1, (
                f"{sid}: PV01 for key bucket {key_bucket} too small: {key_val} vs max {max_val}"
            )

def test_pv01_magnitude(results, portfolio):
    """PV01 magnitudes proportional to notional x duration."""
    for sw in portfolio["swaps"]:
        sid = sw["id"]
        notional = sw["notional"]
        tenor_y = sw["tenor_months"] / 12.0
        pv01 = results["bucketed_pv01"][sid]
        total_abs = sum(abs(v) for v in pv01.values())

        expected_order = notional * (tenor_y / 2) * 1e-4
        assert total_abs > expected_order * 0.05, (
            f"{sid}: total |PV01| {total_abs} too small (expected order {expected_order})"
        )
        assert total_abs < expected_order * 20, (
            f"{sid}: total |PV01| {total_abs} too large (expected order {expected_order})"
        )

# ────────────────────── test 7: forward rate coverage ──────────────────────

def test_forward_rate_coverage(results, market, holidays):
    """Forward rates cover all business days from val_date to last node."""
    val_date = pd(market["valuation_date"])
    last_node = pd(market["node_dates"][-1])
    fwd_dates = set(results["forward_overnight_rates"].keys())

    d = val_date
    expected = 0
    while d <= last_node:
        if is_bd(d, holidays):
            expected += 1
        d += timedelta(days=1)

    actual = len(fwd_dates)
    assert actual >= expected - 2, f"Forward rates: expected ~{expected}, got {actual}"
    assert actual <= expected + 5, f"Forward rates: too many, expected ~{expected}, got {actual}"

def test_forward_rates_positive(results):
    """All forward overnight rates should be positive."""
    for d_str, r in results["forward_overnight_rates"].items():
        assert r > 0, f"Forward rate at {d_str} is non-positive: {r}"

# ────────────────────── test 8: DF/forward consistency ──────────────────────

def test_df_forward_consistency(results, market, holidays):
    """DFs at node dates consistent with compounding forward overnight rates."""
    val_date = pd(market["valuation_date"])
    fwds = results["forward_overnight_rates"]
    dfs_output = results["discount_factors"]

    bd_dates = sorted(pd(d) for d in fwds.keys())
    df_running = {val_date: 1.0}

    for i, bd in enumerate(bd_dates):
        r = fwds[bd.isoformat()]
        if i + 1 < len(bd_dates):
            nxt = bd_dates[i + 1]
        else:
            nxt = bd + timedelta(days=1)
            while not is_bd(nxt, holidays):
                nxt += timedelta(days=1)
        dc = dcf(bd, nxt)
        df_running[nxt] = df_running[bd] / (1 + r * dc)

    for nd_str, df_out in dfs_output.items():
        nd = pd(nd_str)
        if nd in df_running:
            err = abs(df_running[nd] - df_out) / abs(df_out)
            assert err < 1e-6, (
                f"DF inconsistency at {nd_str}: from fwds={df_running[nd]:.10f}, "
                f"reported={df_out:.10f}, rel_err={err:.2e}"
            )

# ────────────────────── test 9: SQLite output ──────────────────────

def test_sqlite_output(results, market, portfolio):
    """SQLite output exists with correct schema and data consistent with JSON."""
    conn = sqlite3.connect("/app/output/curves.db")
    c = conn.cursor()

    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in c.fetchall()}
    for t in ["discount_factors", "forward_rates", "swap_pvs", "bucketed_pv01"]:
        assert t in tables, f"Missing table in curves.db: {t}"

    # discount_factors: cross-check with JSON
    c.execute("SELECT node_date, df FROM discount_factors")
    db_dfs = {r[0]: r[1] for r in c.fetchall()}
    for nd in market["node_dates"]:
        assert nd in db_dfs, f"Missing DF in curves.db for {nd}"
        json_df = results["discount_factors"][nd]
        assert abs(db_dfs[nd] - json_df) < 1e-10, (
            f"DF mismatch at {nd}: sqlite={db_dfs[nd]}, json={json_df}"
        )

    # forward_rates: count matches JSON
    c.execute("SELECT COUNT(*) FROM forward_rates")
    db_count = c.fetchone()[0]
    json_count = len(results["forward_overnight_rates"])
    assert db_count == json_count, (
        f"forward_rates count mismatch: sqlite={db_count}, json={json_count}"
    )

    # spot-check a few forward rates
    c.execute("SELECT business_date, rate FROM forward_rates LIMIT 20")
    for bd_str, db_rate in c.fetchall():
        assert bd_str in results["forward_overnight_rates"], (
            f"Forward rate date {bd_str} in sqlite but not json"
        )
        json_rate = results["forward_overnight_rates"][bd_str]
        assert abs(db_rate - json_rate) < 1e-10, (
            f"Forward rate mismatch at {bd_str}: sqlite={db_rate}, json={json_rate}"
        )

    # swap_pvs: cross-check
    c.execute("SELECT swap_id, pv FROM swap_pvs")
    db_pvs = {r[0]: r[1] for r in c.fetchall()}
    for sw in portfolio["swaps"]:
        sid = sw["id"]
        assert sid in db_pvs, f"Missing PV in curves.db for {sid}"
        json_pv = results["swap_pvs"][sid]
        assert abs(db_pvs[sid] - json_pv) < 0.01, (
            f"PV mismatch for {sid}: sqlite={db_pvs[sid]}, json={json_pv}"
        )

    # bucketed_pv01: verify row counts
    c.execute("SELECT COUNT(DISTINCT swap_id) FROM bucketed_pv01")
    db_swap_count = c.fetchone()[0]
    assert db_swap_count == len(portfolio["swaps"]), (
        f"bucketed_pv01 swap count: sqlite={db_swap_count}, expected={len(portfolio['swaps'])}"
    )
    num_quotes = len(market["ois_quotes"])
    c.execute("SELECT COUNT(*) FROM bucketed_pv01")
    total_rows = c.fetchone()[0]
    assert total_rows == db_swap_count * num_quotes, (
        f"bucketed_pv01 rows: got={total_rows}, expected={db_swap_count * num_quotes}"
    )

    conn.close()

# ────────────────────── test 10: Makefile structure ──────────────────────

def test_makefile_structure():
    """Makefile exists with required targets and tool references."""
    makefile_path = "/app/Makefile"
    assert os.path.isfile(makefile_path), "Makefile not found at /app/Makefile"
    with open(makefile_path) as f:
        content = f.read()

    # Check all required targets exist
    for target in ["calibrate", "report", "views", "all"]:
        assert re.search(rf'^{target}\s*:', content, re.MULTILINE), (
            f"Missing Makefile target: {target}"
        )

    # Parse recipe lines per target to verify tool usage
    lines = content.split('\n')
    current_target = None
    target_recipes = {}
    for line in lines:
        m = re.match(r'^([a-zA-Z_]\w*)\s*:', line)
        if m:
            current_target = m.group(1)
            target_recipes[current_target] = ''
        elif current_target and (line.startswith('\t') or line.startswith('    ')):
            target_recipes[current_target] += line + '\n'

    assert 'jq' in target_recipes.get('report', ''), (
        "report recipe must use jq"
    )
    assert 'sqlite3' in target_recipes.get('views', ''), (
        "views recipe must use sqlite3"
    )

# ────────────────────── test 11: summary.json from jq ──────────────────────

def test_summary_json(results):
    """summary.json produced by jq matches results.json."""
    summary_path = "/app/output/summary.json"
    assert os.path.isfile(summary_path), "summary.json not found at /app/output/summary.json"
    with open(summary_path) as f:
        summary = json.load(f)

    # num_nodes
    assert "num_nodes" in summary, "summary.json missing num_nodes"
    assert summary["num_nodes"] == len(results["discount_factors"]), (
        f"num_nodes: summary={summary['num_nodes']}, "
        f"expected={len(results['discount_factors'])}"
    )

    # num_forward_dates
    assert "num_forward_dates" in summary, "summary.json missing num_forward_dates"
    assert summary["num_forward_dates"] == len(results["forward_overnight_rates"]), (
        f"num_forward_dates: summary={summary['num_forward_dates']}, "
        f"expected={len(results['forward_overnight_rates'])}"
    )

    # min_df / max_df
    df_vals = list(results["discount_factors"].values())
    assert "min_df" in summary, "summary.json missing min_df"
    assert abs(summary["min_df"] - min(df_vals)) < 1e-10, (
        f"min_df: summary={summary['min_df']}, expected={min(df_vals)}"
    )
    assert "max_df" in summary, "summary.json missing max_df"
    assert abs(summary["max_df"] - max(df_vals)) < 1e-10, (
        f"max_df: summary={summary['max_df']}, expected={max(df_vals)}"
    )

    # swap_ids
    assert "swap_ids" in summary, "summary.json missing swap_ids"
    assert set(summary["swap_ids"]) == set(results["swap_pvs"].keys()), (
        f"swap_ids mismatch: summary={summary['swap_ids']}, "
        f"expected={list(results['swap_pvs'].keys())}"
    )

    # total_abs_pv01
    assert "total_abs_pv01" in summary, "summary.json missing total_abs_pv01"
    for sid, pv01_dict in results["bucketed_pv01"].items():
        expected_total = sum(abs(v) for v in pv01_dict.values())
        actual_total = summary["total_abs_pv01"][sid]
        assert abs(actual_total - expected_total) < 0.01, (
            f"total_abs_pv01 mismatch for {sid}: summary={actual_total}, "
            f"expected={expected_total}"
        )

# ────────────────────── test 12: SQL views ──────────────────────

def test_sql_views(results, market, portfolio):
    """SQL views df_monthly and rate_stats exist with correct schema and data."""
    conn = sqlite3.connect("/app/output/curves.db")
    c = conn.cursor()

    # Check df_monthly view exists
    c.execute("SELECT name FROM sqlite_master WHERE type='view' AND name='df_monthly'")
    assert c.fetchone() is not None, "View df_monthly not found in curves.db"

    # Check df_monthly data
    c.execute("SELECT month, min_df FROM df_monthly ORDER BY month")
    rows = c.fetchall()
    assert len(rows) > 0, "df_monthly view returned no rows"
    for month_str, min_df in rows:
        assert len(month_str) == 7 and month_str[4] == '-', (
            f"month format should be YYYY-MM, got '{month_str}'"
        )
        assert 0 < min_df < 1, f"min_df out of range for {month_str}: {min_df}"

    # Verify df_monthly values against discount_factors table
    c.execute("SELECT substr(node_date, 1, 7) AS m, MIN(df) FROM discount_factors GROUP BY m")
    expected_monthly = {r[0]: r[1] for r in c.fetchall()}
    view_monthly = {r[0]: r[1] for r in rows}
    for m, edf in expected_monthly.items():
        assert m in view_monthly, f"df_monthly missing month {m}"
        assert abs(view_monthly[m] - edf) < 1e-12, (
            f"df_monthly mismatch for {m}: view={view_monthly[m]}, expected={edf}"
        )

    # Check rate_stats view exists
    c.execute("SELECT name FROM sqlite_master WHERE type='view' AND name='rate_stats'")
    assert c.fetchone() is not None, "View rate_stats not found in curves.db"

    # Check rate_stats data
    c.execute("SELECT swap_id, total_pv01, max_abs_bucket FROM rate_stats")
    rs_rows = c.fetchall()
    assert len(rs_rows) == len(portfolio["swaps"]), (
        f"rate_stats row count: {len(rs_rows)}, expected {len(portfolio['swaps'])}"
    )

    # Cross-check rate_stats with bucketed_pv01 table
    for swap_id, total_pv01, max_abs_bucket in rs_rows:
        assert swap_id in results["bucketed_pv01"], (
            f"rate_stats swap_id '{swap_id}' not in results"
        )
        pv01_dict = results["bucketed_pv01"][swap_id]
        expected_total = sum(pv01_dict.values())
        expected_max_abs = max(abs(v) for v in pv01_dict.values())
        assert abs(total_pv01 - expected_total) < 0.01, (
            f"rate_stats total_pv01 mismatch for {swap_id}: "
            f"view={total_pv01}, expected={expected_total}"
        )
        assert abs(max_abs_bucket - expected_max_abs) < 0.01, (
            f"rate_stats max_abs_bucket mismatch for {swap_id}: "
            f"view={max_abs_bucket}, expected={expected_max_abs}"
        )

    conn.close()
