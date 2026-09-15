#!/usr/bin/env python3

"""
Macroeconomic Regime Analysis Pipeline
Reads FRED data from CSV files and a SQLite database, computes 5 derived indicators,
stores results in /app/results.db.
"""

import csv
import math
import sqlite3
import os
from collections import defaultdict

DATA_DIR = "/app/data"
DB_FILE = f"{DATA_DIR}/macro.db"
RESULTS_DB = "/app/results.db"


def load_csv(filename):
    """Load a FRED CSV, returning list of (date_str, value_or_None)."""
    rows = []
    with open(f"{DATA_DIR}/{filename}") as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            date_str = row[0]
            val_str = row[1].strip() if len(row) > 1 else ""
            if val_str == "" or val_str == ".":
                rows.append((date_str, None))
            else:
                rows.append((date_str, float(val_str)))
    return rows


def load_csv_valid(filename):
    """Load CSV, returning only rows with valid values."""
    return [(d, v) for d, v in load_csv(filename) if v is not None]


def load_db_series(series_id):
    """Load a series from the SQLite observations table."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.execute(
        "SELECT observation_date, value FROM observations "
        "WHERE series_id = ? ORDER BY observation_date",
        (series_id,)
    )
    rows = []
    for date_str, val_str in cursor:
        val_str = (val_str or "").strip()
        if val_str == "" or val_str == ".":
            rows.append((date_str, None))
        else:
            rows.append((date_str, float(val_str)))
    conn.close()
    return rows


def load_db_series_valid(series_id):
    """Load series from DB, returning only rows with valid values."""
    return [(d, v) for d, v in load_db_series(series_id) if v is not None]


def compute_yield_curve_inversions():
    """Identify continuous periods where T10Y2Y spread < 0, lasting >= 5 business days."""
    data = load_csv("T10Y2Y.csv")

    inversions = []
    in_inversion = False
    start_date = None
    min_spread = None
    biz_days = 0
    prev_date = None

    for date_str, val in data:
        if val is None:
            continue
        if val < 0:
            if not in_inversion:
                in_inversion = True
                start_date = date_str
                min_spread = val
                biz_days = 1
            else:
                biz_days += 1
                if val < min_spread:
                    min_spread = val
        else:
            if in_inversion:
                inversions.append({
                    "start_date": start_date,
                    "end_date": prev_date,
                    "business_days": biz_days,
                    "min_spread": round(min_spread, 4),
                })
                in_inversion = False
        prev_date = date_str

    if in_inversion:
        inversions.append({
            "start_date": start_date,
            "end_date": prev_date,
            "business_days": biz_days,
            "min_spread": round(min_spread, 4),
        })

    return [inv for inv in inversions if inv["business_days"] >= 5]


def compute_sahm_rule_episodes():
    """Compute Sahm Rule episodes from UNRATE (stored in SQLite)."""
    unrate = load_db_series_valid("UNRATE")

    # Compute 3-month moving averages
    ma3 = []
    for i in range(2, len(unrate)):
        avg = (unrate[i][1] + unrate[i - 1][1] + unrate[i - 2][1]) / 3.0
        ma3.append((unrate[i][0], avg))

    # Compute Sahm indicator: current MA3 minus min of prior 12 MA3 values
    sahm_triggers = []
    for i in range(12, len(ma3)):
        current_ma = ma3[i][1]
        min_ma = min(ma3[j][1] for j in range(i - 12, i))
        indicator = current_ma - min_ma
        if indicator >= 0.50:
            date_ym = ma3[i][0][:7]
            sahm_triggers.append((date_ym, round(indicator, 4)))

    # Group consecutive triggers into episodes
    episodes = []
    current_ep = []
    prev_ym = None

    for ym, val in sahm_triggers:
        if prev_ym is not None:
            py, pm = int(prev_ym[:4]), int(prev_ym[5:7])
            cy, cm = int(ym[:4]), int(ym[5:7])
            expected_m = pm + 1
            expected_y = py
            if expected_m > 12:
                expected_m = 1
                expected_y += 1
            if cy == expected_y and cm == expected_m:
                current_ep.append((ym, val))
            else:
                episodes.append(current_ep)
                current_ep = [(ym, val)]
        else:
            current_ep = [(ym, val)]
        prev_ym = ym

    if current_ep:
        episodes.append(current_ep)

    result = []
    for ep in episodes:
        result.append({
            "start_date": ep[0][0],
            "end_date": ep[-1][0],
            "peak_indicator": round(max(v for _, v in ep), 4),
        })

    return result


def compute_real_ffr():
    """Compute real federal funds rate = FEDFUNDS - YoY CPI inflation."""
    cpi_data = load_csv_valid("CPIAUCSL.csv")
    ff_data = load_db_series_valid("FEDFUNDS")

    # Build CPI dict by YYYY-MM
    cpi_dict = {}
    for d, v in cpi_data:
        cpi_dict[d[:7]] = v

    # Compute YoY inflation
    inflation_dict = {}
    for d, v in cpi_data:
        ym = d[:7]
        y, m = int(ym[:4]), int(ym[5:7])
        prev_ym = f"{y - 1}-{m:02d}"
        if prev_ym in cpi_dict:
            inflation_dict[ym] = ((v - cpi_dict[prev_ym]) / cpi_dict[prev_ym]) * 100.0

    # Build FEDFUNDS dict
    ff_dict = {}
    for d, v in ff_data:
        ff_dict[d[:7]] = v

    # Compute real FFR
    real_ffr = []
    for ym in sorted(inflation_dict.keys()):
        if ym in ff_dict:
            r = ff_dict[ym] - inflation_dict[ym]
            real_ffr.append((ym, r))

    # Find max/min
    max_rffr = max(real_ffr, key=lambda x: x[1])
    min_rffr = min(real_ffr, key=lambda x: x[1])

    # Decade averages
    decades = defaultdict(list)
    for ym, r in real_ffr:
        decade = int(ym[:3]) * 10
        decade_key = f"{decade}s"
        decades[decade_key].append(r)

    decade_averages = {}
    for dk in sorted(decades.keys()):
        decade_averages[dk] = round(sum(decades[dk]) / len(decades[dk]), 4)

    return {
        "max": {"date": max_rffr[0], "value": round(max_rffr[1], 4)},
        "min": {"date": min_rffr[0], "value": round(min_rffr[1], 4)},
        "decade_averages": decade_averages,
    }


def compute_m2_growth():
    """Compute YoY M2 growth and classify into regimes."""
    m2_data = load_db_series_valid("M2SL")

    # Build dict
    m2_dict = {}
    for d, v in m2_data:
        m2_dict[d[:7]] = v

    # Compute YoY growth
    m2_growth = []
    for d, v in m2_data:
        ym = d[:7]
        y, m = int(ym[:4]), int(ym[5:7])
        prev_ym = f"{y - 1}-{m:02d}"
        if prev_ym in m2_dict:
            growth = ((v - m2_dict[prev_ym]) / m2_dict[prev_ym]) * 100.0
            m2_growth.append((ym, growth))

    # Classify regimes
    regime_counts = {"contraction": 0, "low": 0, "moderate": 0, "rapid": 0, "extreme": 0}
    for _, g in m2_growth:
        if g < 0:
            regime_counts["contraction"] += 1
        elif g < 5:
            regime_counts["low"] += 1
        elif g < 10:
            regime_counts["moderate"] += 1
        elif g < 15:
            regime_counts["rapid"] += 1
        else:
            regime_counts["extreme"] += 1

    max_g = max(m2_growth, key=lambda x: x[1])
    min_g = min(m2_growth, key=lambda x: x[1])

    return {
        "regime_counts": regime_counts,
        "max_growth": {"date": max_g[0], "value": round(max_g[1], 4)},
        "min_growth": {"date": min_g[0], "value": round(min_g[1], 4)},
    }


def zscore_population(vals):
    """Compute z-scores using population standard deviation."""
    n = len(vals)
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / n
    std = math.sqrt(var)
    return [(v - mean) / std for v in vals]


def compute_composite_stress():
    """Compute composite stress index from 4 z-scored components."""
    # Component 1: Monthly average T10Y2Y (from CSV)
    t10y2y_raw = load_csv("T10Y2Y.csv")
    monthly_groups = defaultdict(list)
    for d, v in t10y2y_raw:
        if v is not None:
            monthly_groups[d[:7]].append(v)
    t10y2y_monthly = {ym: sum(vs) / len(vs) for ym, vs in monthly_groups.items()}

    # Component 2: 3-month change in UNRATE (from SQLite)
    unrate_data = load_db_series_valid("UNRATE")
    unrate_dict = {d[:7]: v for d, v in unrate_data}
    unrate_3m_change = {}
    for d, v in unrate_data:
        ym = d[:7]
        y, m = int(ym[:4]), int(ym[5:7])
        pm, py = m - 3, y
        if pm <= 0:
            pm += 12
            py -= 1
        prev_ym = f"{py}-{pm:02d}"
        if prev_ym in unrate_dict:
            unrate_3m_change[ym] = v - unrate_dict[prev_ym]

    # Component 3: Real FFR (CPI from CSV, FEDFUNDS from SQLite)
    cpi_data = load_csv_valid("CPIAUCSL.csv")
    cpi_dict = {d[:7]: v for d, v in cpi_data}
    inflation_dict = {}
    for d, v in cpi_data:
        ym = d[:7]
        y, m = int(ym[:4]), int(ym[5:7])
        prev_ym = f"{y - 1}-{m:02d}"
        if prev_ym in cpi_dict:
            inflation_dict[ym] = ((v - cpi_dict[prev_ym]) / cpi_dict[prev_ym]) * 100.0

    ff_data = load_db_series_valid("FEDFUNDS")
    ff_dict = {d[:7]: v for d, v in ff_data}
    real_ffr_dict = {}
    for ym in inflation_dict:
        if ym in ff_dict:
            real_ffr_dict[ym] = ff_dict[ym] - inflation_dict[ym]

    # Component 4: M2 YoY growth (from SQLite)
    m2_data = load_db_series_valid("M2SL")
    m2_dict = {d[:7]: v for d, v in m2_data}
    m2_growth_dict = {}
    for d, v in m2_data:
        ym = d[:7]
        y, m = int(ym[:4]), int(ym[5:7])
        prev_ym = f"{y - 1}-{m:02d}"
        if prev_ym in m2_dict:
            m2_growth_dict[ym] = ((v - m2_dict[prev_ym]) / m2_dict[prev_ym]) * 100.0

    # Find overlapping months
    all_months = sorted(
        set(t10y2y_monthly.keys())
        & set(unrate_3m_change.keys())
        & set(real_ffr_dict.keys())
        & set(m2_growth_dict.keys())
    )

    vals1 = [t10y2y_monthly[m] for m in all_months]
    vals2 = [unrate_3m_change[m] for m in all_months]
    vals3 = [real_ffr_dict[m] for m in all_months]
    vals4 = [m2_growth_dict[m] for m in all_months]

    z1 = zscore_population(vals1)
    z2 = zscore_population(vals2)
    z3 = zscore_population(vals3)
    z4 = zscore_population(vals4)

    stress_months = []
    for i, m in enumerate(all_months):
        score = -z1[i] + z2[i] + z3[i] - z4[i]
        if score > 2.0:
            stress_months.append({"date": m, "score": round(score, 4)})

    max_stress = max(stress_months, key=lambda x: x["score"])

    return {
        "stress_months": stress_months,
        "max_stress": {"date": max_stress["date"], "score": max_stress["score"]},
        "count": len(stress_months),
    }


def main():
    inversions = compute_yield_curve_inversions()
    sahm_episodes = compute_sahm_rule_episodes()
    real_ffr = compute_real_ffr()
    m2 = compute_m2_growth()
    stress = compute_composite_stress()

    # Write results to SQLite database
    if os.path.exists(RESULTS_DB):
        os.remove(RESULTS_DB)

    conn = sqlite3.connect(RESULTS_DB)
    cur = conn.cursor()

    cur.execute("""CREATE TABLE yield_curve_inversions (
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        business_days INTEGER NOT NULL,
        min_spread REAL NOT NULL
    )""")
    for inv in inversions:
        cur.execute(
            "INSERT INTO yield_curve_inversions VALUES (?,?,?,?)",
            (inv["start_date"], inv["end_date"], inv["business_days"], inv["min_spread"]),
        )

    cur.execute("""CREATE TABLE sahm_rule_episodes (
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        peak_indicator REAL NOT NULL
    )""")
    for ep in sahm_episodes:
        cur.execute(
            "INSERT INTO sahm_rule_episodes VALUES (?,?,?)",
            (ep["start_date"], ep["end_date"], ep["peak_indicator"]),
        )

    cur.execute("""CREATE TABLE real_ffr_extremes (
        type TEXT NOT NULL,
        date TEXT NOT NULL,
        value REAL NOT NULL
    )""")
    cur.execute(
        "INSERT INTO real_ffr_extremes VALUES (?,?,?)",
        ("max", real_ffr["max"]["date"], real_ffr["max"]["value"]),
    )
    cur.execute(
        "INSERT INTO real_ffr_extremes VALUES (?,?,?)",
        ("min", real_ffr["min"]["date"], real_ffr["min"]["value"]),
    )

    cur.execute("""CREATE TABLE real_ffr_decades (
        decade TEXT NOT NULL,
        average REAL NOT NULL
    )""")
    for decade, avg in real_ffr["decade_averages"].items():
        cur.execute("INSERT INTO real_ffr_decades VALUES (?,?)", (decade, avg))

    cur.execute("""CREATE TABLE m2_regime_counts (
        regime TEXT NOT NULL,
        cnt INTEGER NOT NULL
    )""")
    for regime, count in m2["regime_counts"].items():
        cur.execute("INSERT INTO m2_regime_counts VALUES (?,?)", (regime, count))

    cur.execute("""CREATE TABLE m2_growth_extremes (
        type TEXT NOT NULL,
        date TEXT NOT NULL,
        value REAL NOT NULL
    )""")
    cur.execute(
        "INSERT INTO m2_growth_extremes VALUES (?,?,?)",
        ("max", m2["max_growth"]["date"], m2["max_growth"]["value"]),
    )
    cur.execute(
        "INSERT INTO m2_growth_extremes VALUES (?,?,?)",
        ("min", m2["min_growth"]["date"], m2["min_growth"]["value"]),
    )

    cur.execute("""CREATE TABLE composite_stress_months (
        date TEXT NOT NULL,
        score REAL NOT NULL
    )""")
    for entry in stress["stress_months"]:
        cur.execute(
            "INSERT INTO composite_stress_months VALUES (?,?)",
            (entry["date"], entry["score"]),
        )

    conn.commit()
    conn.close()

    print(f"Results database written to {RESULTS_DB}")
    print(f"  Yield curve inversions: {len(inversions)}")
    print(f"  Sahm Rule episodes: {len(sahm_episodes)}")
    print(f"  Real FFR max: {real_ffr['max']}")
    print(f"  M2 growth regimes: {m2['regime_counts']}")
    print(f"  Composite stress months: {stress['count']}")


if __name__ == "__main__":
    main()
