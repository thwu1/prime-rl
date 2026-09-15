#!/usr/bin/env python3
"""
Multi-curve OIS framework with intra-month seasonality derived from historical fixings.

"""

import json
import math
import csv
import sqlite3
import calendar as cal_mod
import os
import bisect
from datetime import date, timedelta
from collections import defaultdict

# ────────────────────────────────────────────────────────────
# I/O: JSON market data
# ────────────────────────────────────────────────────────────

def load_market_json(market_path, holidays_path):
    with open(market_path) as f:
        data = json.load(f)
    val_date = data["valuation_date"]
    ois_quotes = data["ois_quotes"]
    node_dates = data["node_dates"]
    with open(holidays_path) as f:
        hol_data = json.load(f)
    holidays = set(date.fromisoformat(d) for d in hol_data["us_holidays"])
    return val_date, ois_quotes, node_dates, holidays

# ────────────────────────────────────────────────────────────
# I/O: YAML portfolio
# ────────────────────────────────────────────────────────────

def load_portfolio(path):
    import yaml
    with open(path) as f:
        return yaml.safe_load(f)

# ────────────────────────────────────────────────────────────
# I/O: CSV fixings
# ────────────────────────────────────────────────────────────

def load_fixings(path):
    fixings = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            fixings.append((date.fromisoformat(row["date"]), float(row["rate"])))
    return fixings

# ────────────────────────────────────────────────────────────
# Linear algebra
# ────────────────────────────────────────────────────────────

def solve_linear(A, b):
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        max_row = col
        for r in range(col + 1, n):
            if abs(M[r][col]) > abs(M[max_row][col]):
                max_row = r
        M[col], M[max_row] = M[max_row], M[col]
        pivot = M[col][col]
        if abs(pivot) < 1e-30:
            raise ValueError("Singular matrix")
        for r in range(col + 1, n):
            factor = M[r][col] / pivot
            for c in range(col, n + 1):
                M[r][c] -= factor * M[col][c]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = M[i][n]
        for j in range(i + 1, n):
            s -= M[i][j] * x[j]
        x[i] = s / M[i][i]
    return x

# ────────────────────────────────────────────────────────────
# Date / calendar utilities
# ────────────────────────────────────────────────────────────

def is_bd(d, hols):
    return d.weekday() < 5 and d not in hols

def next_bd(d, hols):
    d = d + timedelta(days=1)
    while not is_bd(d, hols):
        d += timedelta(days=1)
    return d

def prev_bd(d, hols):
    d = d - timedelta(days=1)
    while not is_bd(d, hols):
        d -= timedelta(days=1)
    return d

def mod_fol(d, hols):
    if is_bd(d, hols):
        return d
    orig_month = d.month
    nxt = d
    while not is_bd(nxt, hols):
        nxt += timedelta(days=1)
    if nxt.month != orig_month:
        prv = d
        while not is_bd(prv, hols):
            prv -= timedelta(days=1)
        return prv
    return nxt

def add_months(d, months):
    total_m = d.month + months
    y = d.year + (total_m - 1) // 12
    m = (total_m - 1) % 12 + 1
    max_day = cal_mod.monthrange(y, m)[1]
    return date(y, m, min(d.day, max_day))

def dcf360(d1, d2):
    return (d2 - d1).days / 360.0

def list_bds(start, end, hols):
    result = []
    d = start
    while d <= end:
        if is_bd(d, hols):
            result.append(d)
        d += timedelta(days=1)
    return result

def ds(d):
    return d.isoformat()

# ────────────────────────────────────────────────────────────
# Seasonality extraction from historical fixings
# ────────────────────────────────────────────────────────────

def classify_bd_from_list(d, month_bds):
    """Classify a business day using the dates present in the fixings for that month."""
    if d == month_bds[-1]:
        return "month_end"
    if d == month_bds[0]:
        return "first_bd"
    if len(month_bds) >= 2 and d == month_bds[1]:
        return "second_bd"
    if len(month_bds) >= 2 and d == month_bds[-2]:
        return "second_last_bd"
    for bd in month_bds:
        if bd.day >= 15:
            if d == bd:
                return "fifteenth"
            break
    return "other"

def extract_seasonality(fixings):
    """Extract seasonality spreads (in bps) from historical fixings by comparing
    each category to 'other' days within the same month."""
    by_month = defaultdict(list)
    for d, r in fixings:
        by_month[(d.year, d.month)].append((d, r))

    cats = defaultdict(list)
    for key in sorted(by_month.keys()):
        entries = sorted(by_month[key])
        month_bds = [d for d, r in entries]
        rates = {d: r for d, r in entries}

        other_rates = [rates[d] for d in month_bds
                       if classify_bd_from_list(d, month_bds) == "other"]
        if not other_rates:
            continue
        avg_other = sum(other_rates) / len(other_rates)

        for d in month_bds:
            cat = classify_bd_from_list(d, month_bds)
            cats[cat].append((rates[d] - avg_other) * 10000)

    result = {}
    for cat in ["month_end", "first_bd", "second_bd", "fifteenth", "second_last_bd", "other"]:
        if cats[cat]:
            result[cat] = sum(cats[cat]) / len(cats[cat])
        else:
            result[cat] = 0.0
    return result

# ────────────────────────────────────────────────────────────
# Seasonality classification (for curve construction)
# ────────────────────────────────────────────────────────────

def classify_bd(d, hols):
    y, m = d.year, d.month
    max_day = cal_mod.monthrange(y, m)[1]
    lbd = date(y, m, max_day)
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

# ────────────────────────────────────────────────────────────
# Seasonality curve: D_seas
# ────────────────────────────────────────────────────────────

class SeasCurve:
    def __init__(self, val_date, end_date, hols, seas_bps):
        bds = list_bds(val_date, end_date, hols)
        self._log = {}
        self._bds = bds
        cum = 0.0
        for i, bd in enumerate(bds):
            self._log[bd] = cum
            if i < len(bds) - 1:
                nxt = bds[i + 1]
                cat = classify_bd(bd, hols)
                spread = seas_bps.get(cat, 0.0) / 10000.0
                cum -= spread * dcf360(bd, nxt)

    def log_df(self, d):
        if d in self._log:
            return self._log[d]
        idx = bisect.bisect_right(self._bds, d)
        if idx == 0:
            return 0.0
        if idx >= len(self._bds):
            return self._log[self._bds[-1]]
        p, n = self._bds[idx - 1], self._bds[idx]
        alpha = (d - p).days / (n - p).days
        return self._log[p] * (1 - alpha) + self._log[n] * alpha

    def df(self, d):
        return math.exp(self.log_df(d))

# ────────────────────────────────────────────────────────────
# Variable curve: D_var (log-linear on DF with nodes)
# ────────────────────────────────────────────────────────────

class VarCurve:
    def __init__(self, val_date, node_dates, log_dfs):
        self.val = val_date
        self.nodes = node_dates
        self.x = list(log_dfs)
        self.t = [(nd - val_date).days for nd in node_dates]

    def log_df(self, d):
        t = (d - self.val).days
        if t <= 0:
            return 0.0
        if t <= self.t[0]:
            return self.x[0] * t / self.t[0]
        for i in range(len(self.t) - 1):
            if self.t[i] <= t <= self.t[i + 1]:
                alpha = (t - self.t[i]) / (self.t[i + 1] - self.t[i])
                return self.x[i] * (1 - alpha) + self.x[i + 1] * alpha
        n = len(self.t)
        fwd = (self.x[n - 1] - self.x[n - 2]) / (self.t[n - 1] - self.t[n - 2])
        return self.x[n - 1] + fwd * (t - self.t[n - 1])

    def df(self, d):
        return math.exp(self.log_df(d))

def total_df(d, var_c, seas_c):
    return var_c.df(d) * seas_c.df(d)

# ────────────────────────────────────────────────────────────
# Swap mechanics
# ────────────────────────────────────────────────────────────

def payment_dates(effective, maturity, freq_months, hols):
    dates = []
    n = 1
    while True:
        raw = add_months(effective, freq_months * n)
        if raw >= maturity:
            adj = mod_fol(maturity, hols)
            if not dates or dates[-1] != adj:
                dates.append(adj)
            break
        dates.append(mod_fol(raw, hols))
        n += 1
    return dates

def swap_rate(eff, mat, pdates, df_func):
    ann = 0.0
    prev = eff
    for pd in pdates:
        ann += dcf360(prev, pd) * df_func(pd)
        prev = pd
    flt = df_func(eff) - df_func(mat)
    if abs(ann) < 1e-15:
        return 0.0
    return flt / ann

def swap_pv(direction, notional, fixed_r, eff, mat, pdates, df_func):
    ann = 0.0
    prev = eff
    for pd in pdates:
        ann += dcf360(prev, pd) * df_func(pd)
        prev = pd
    fixed_pv = fixed_r * ann
    float_pv = df_func(eff) - df_func(mat)
    if direction == "receiver":
        return notional * (fixed_pv - float_pv)
    else:
        return notional * (float_pv - fixed_pv)

# ────────────────────────────────────────────────────────────
# Calibration
# ────────────────────────────────────────────────────────────

def build_swap_specs(ois_quotes, eff, hols):
    specs = []
    for q in ois_quotes:
        tm = q["tenor_months"]
        mat = mod_fol(add_months(eff, tm), hols)
        freq = 12 if tm <= 12 else 6
        pds = payment_dates(eff, mat, freq, hols)
        specs.append({"rate": q["rate"], "eff": eff, "mat": mat, "pds": pds})
    return specs

def calibrate(ois_quotes, node_dates, val_date, hols, seas_c):
    eff = val_date
    for _ in range(2):
        eff = next_bd(eff, hols)

    specs = build_swap_specs(ois_quotes, eff, hols)
    N = len(node_dates)

    avg_r = sum(q["rate"] for q in ois_quotes) / len(ois_quotes)
    x = [-avg_r * (nd - val_date).days / 365.0 for nd in node_dates]

    for iteration in range(60):
        vc = VarCurve(val_date, node_dates, x)
        df_fn = lambda d, _vc=vc: total_df(d, _vc, seas_c)

        F = [swap_rate(s["eff"], s["mat"], s["pds"], df_fn) - s["rate"] for s in specs]
        max_err = max(abs(f) for f in F)
        if max_err < 1e-14:
            break

        eps = 1e-8
        J = [[0.0] * N for _ in range(N)]
        for k in range(N):
            xk = x[:]
            xk[k] += eps
            vc_k = VarCurve(val_date, node_dates, xk)
            df_k = lambda d, _vc=vc_k: total_df(d, _vc, seas_c)
            for i, s in enumerate(specs):
                J[i][k] = (swap_rate(s["eff"], s["mat"], s["pds"], df_k) - (F[i] + s["rate"])) / eps

        dx = solve_linear(J, [-f for f in F])
        x = [x[i] + dx[i] for i in range(N)]

    return VarCurve(val_date, node_dates, x)

# ────────────────────────────────────────────────────────────
# Forward rates
# ────────────────────────────────────────────────────────────

def forward_rates(val_date, end_date, hols, var_c, seas_c):
    extended = end_date + timedelta(days=10)
    bds = list_bds(val_date, extended, hols)
    fwds = {}
    for i in range(len(bds) - 1):
        d, d2 = bds[i], bds[i + 1]
        if d > end_date:
            break
        df_d = total_df(d, var_c, seas_c)
        df_d2 = total_df(d2, var_c, seas_c)
        dc = dcf360(d, d2)
        fwds[ds(d)] = (df_d / df_d2 - 1) / dc if dc > 0 else 0.0
    return fwds

# ────────────────────────────────────────────────────────────
# Bucketed PV01
# ────────────────────────────────────────────────────────────

def bucketed_pv01(sw_info, ois_quotes, node_dates, val_date, hols, seas_c, base_vc):
    eff = val_date
    for _ in range(2):
        eff = next_bd(eff, hols)
    tm = sw_info["tenor_months"]
    mat = mod_fol(add_months(eff, tm), hols)
    freq = 12 if tm <= 12 else 6
    pds = payment_dates(eff, mat, freq, hols)

    df_base = lambda d: total_df(d, base_vc, seas_c)
    base_pv = swap_pv(sw_info["direction"], sw_info["notional"],
                       sw_info["fixed_rate"], eff, mat, pds, df_base)

    bump = 1e-4
    result = {}
    for j, q in enumerate(ois_quotes):
        bumped = [dict(qq) for qq in ois_quotes]
        bumped[j]["rate"] += bump
        bvc = calibrate(bumped, node_dates, val_date, hols, seas_c)
        df_b = lambda d, _bvc=bvc: total_df(d, _bvc, seas_c)
        bpv = swap_pv(sw_info["direction"], sw_info["notional"],
                       sw_info["fixed_rate"], eff, mat, pds, df_b)
        result[q["label"]] = bpv - base_pv
    return result

# ────────────────────────────────────────────────────────────
# SQLite output writer
# ────────────────────────────────────────────────────────────

def write_sqlite_output(path, dfs, fwds, spvs, bpv01):
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    c = conn.cursor()

    c.execute("CREATE TABLE discount_factors (node_date TEXT PRIMARY KEY, df REAL NOT NULL)")
    for nd, df in dfs.items():
        c.execute("INSERT INTO discount_factors VALUES (?, ?)", (nd, df))

    c.execute("CREATE TABLE forward_rates (business_date TEXT PRIMARY KEY, rate REAL NOT NULL)")
    for bd, r in fwds.items():
        c.execute("INSERT INTO forward_rates VALUES (?, ?)", (bd, r))

    c.execute("CREATE TABLE swap_pvs (swap_id TEXT PRIMARY KEY, pv REAL NOT NULL)")
    for sid, pv in spvs.items():
        c.execute("INSERT INTO swap_pvs VALUES (?, ?)", (sid, pv))

    c.execute("""CREATE TABLE bucketed_pv01 (
        swap_id TEXT NOT NULL,
        tenor_label TEXT NOT NULL,
        pv01 REAL NOT NULL,
        PRIMARY KEY (swap_id, tenor_label)
    )""")
    for sid, buckets in bpv01.items():
        for label, val in buckets.items():
            c.execute("INSERT INTO bucketed_pv01 VALUES (?, ?, ?)", (sid, label, val))

    conn.commit()
    conn.close()

# ────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────

def main():
    # Load inputs from JSON and CSV sources
    val_date_str, ois_q, node_date_strs, hols = load_market_json(
        "/app/data/market_data.json", "/app/data/holidays.json"
    )
    pf = load_portfolio("/app/data/portfolio.yaml")
    fixings = load_fixings("/app/data/sofr_fixings.csv")

    val_date = date.fromisoformat(val_date_str)
    node_dates = [date.fromisoformat(d) for d in node_date_strs]

    # Extract seasonality from historical fixings
    seas_bps = extract_seasonality(fixings)

    end_date = max(node_dates) + timedelta(days=30)
    seas_c = SeasCurve(val_date, end_date, hols, seas_bps)
    var_c = calibrate(ois_q, node_dates, val_date, hols, seas_c)

    # Discount factors at nodes
    dfs = {ds(nd): total_df(nd, var_c, seas_c) for nd in node_dates}

    # Forward overnight rates
    fwds = forward_rates(val_date, max(node_dates), hols, var_c, seas_c)

    # Portfolio pricing
    eff = val_date
    for _ in range(2):
        eff = next_bd(eff, hols)

    spvs = {}
    bpv01 = {}
    for sw in pf["swaps"]:
        sid = sw["id"]
        tm = sw["tenor_months"]
        mat = mod_fol(add_months(eff, tm), hols)
        freq = 12 if tm <= 12 else 6
        pds = payment_dates(eff, mat, freq, hols)
        df_fn = lambda d: total_df(d, var_c, seas_c)
        spvs[sid] = swap_pv(sw["direction"], sw["notional"],
                             sw["fixed_rate"], eff, mat, pds, df_fn)
        bpv01[sid] = bucketed_pv01(sw, ois_q, node_dates, val_date, hols, seas_c, var_c)

    os.makedirs("/app/output", exist_ok=True)

    # Write JSON output
    with open("/app/output/results.json", "w") as f:
        json.dump({
            "discount_factors": dfs,
            "forward_overnight_rates": fwds,
            "swap_pvs": spvs,
            "bucketed_pv01": bpv01,
        }, f, indent=2)

    # Write SQLite output
    write_sqlite_output("/app/output/curves.db", dfs, fwds, spvs, bpv01)

if __name__ == "__main__":
    main()
