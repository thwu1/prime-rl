#!/usr/bin/env python3
"""
FRED Multi-Series Economic Indicator Pipeline — Reference Solution.

Reads 8 FRED CSV data files, aligns them to monthly frequency,
computes derived macroeconomic indicators, and writes results to JSON.
"""

import json
import math
import os
import warnings

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.interpolate import CubicSpline
from scipy.sparse.linalg import spsolve

warnings.filterwarnings("ignore", category=DeprecationWarning)


# -- Helpers -----------------------------------------------------------------

def hp_filter(y, lamb=1600):
    """Hodrick-Prescott filter using sparse matrices.

    Returns (trend, cycle) arrays.
    """
    n = len(y)
    K = sparse.diags(
        [np.ones(n - 2), -2 * np.ones(n - 2), np.ones(n - 2)],
        [0, 1, 2],
        shape=(n - 2, n),
        format="csc",
    )
    I = sparse.eye(n, format="csc")
    trend = spsolve(I + lamb * K.T.dot(K), y)
    cycle = y - trend
    return np.asarray(trend), np.asarray(cycle)


def read_fred_csv(filepath):
    """Read a FRED-style CSV, returning DataFrame with columns [date, value]."""
    df = pd.read_csv(filepath)
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["date"])
    return df.sort_values("date").reset_index(drop=True)


def daily_to_monthly(df):
    """Aggregate daily series to monthly average, dropping NaN values."""
    tmp = df.dropna(subset=["value"]).copy()
    tmp["month"] = tmp["date"].dt.to_period("M")
    monthly = tmp.groupby("month")["value"].mean().reset_index()
    monthly["date"] = monthly["month"].dt.to_timestamp()
    return monthly[["date", "value"]].reset_index(drop=True)


def quarterly_to_monthly_spline(q_dates, q_values, monthly_dates):
    """Interpolate quarterly values to monthly via natural cubic spline.

    Quarterly values are assigned to the middle month of each quarter.
    """
    ref = pd.Timestamp("1900-01-01")
    q_mid = [pd.Timestamp(d) + pd.DateOffset(months=1) for d in q_dates]
    q_x = np.array([(d - ref).days for d in q_mid], dtype=float)
    m_x = np.array([(d - ref).days for d in monthly_dates], dtype=float)

    cs = CubicSpline(q_x, np.asarray(q_values, dtype=float), bc_type="natural")
    result = cs(m_x)
    return np.asarray(result, dtype=float)


def safe_val(v):
    """Convert a value to a JSON-safe Python type (None, float, or int)."""
    if v is None:
        return None
    if isinstance(v, (float, np.floating)):
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv):
            return None
        return round(fv, 4)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    try:
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv):
            return None
        return round(fv, 4)
    except (TypeError, ValueError):
        return None


# -- Main pipeline -----------------------------------------------------------

def main():
    DATA_DIR = "/app/data"
    OUTPUT_DIR = "/app/output"
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 1. Read all series
    cpi_raw = read_fred_csv(f"{DATA_DIR}/CPIAUCSL.csv")
    gdp_raw = read_fred_csv(f"{DATA_DIR}/GDP.csv")
    ff_raw = read_fred_csv(f"{DATA_DIR}/FEDFUNDS.csv")
    ur_raw = read_fred_csv(f"{DATA_DIR}/UNRATE.csv")
    m2_raw = read_fred_csv(f"{DATA_DIR}/M2SL.csv")
    dgs10_raw = read_fred_csv(f"{DATA_DIR}/DGS10.csv")
    t10y2y_raw = read_fred_csv(f"{DATA_DIR}/T10Y2Y.csv")
    payems_raw = read_fred_csv(f"{DATA_DIR}/PAYEMS.csv")

    # 2. Aggregate daily series to monthly
    dgs10_m = daily_to_monthly(dgs10_raw).rename(columns={"value": "dgs10"})
    t10y2y_m = daily_to_monthly(t10y2y_raw).rename(columns={"value": "t10y2y"})

    # 3. Build monthly frame for analysis period
    START = pd.Timestamp("1977-01-01")
    END = pd.Timestamp("2025-12-01")
    months = pd.date_range(START, END, freq="MS")
    df = pd.DataFrame({"date": months})

    # Merge monthly series (forward-fill isolated gaps)
    for name, raw in [("cpi", cpi_raw), ("fedfunds", ff_raw),
                       ("unrate", ur_raw), ("m2", m2_raw),
                       ("payems", payems_raw)]:
        tmp = raw.dropna(subset=["value"]).rename(columns={"value": name})
        df = df.merge(tmp[["date", name]], on="date", how="left")
        df[name] = df[name].ffill()

    # Merge aggregated daily series
    df = df.merge(dgs10_m, on="date", how="left")
    df = df.merge(t10y2y_m, on="date", how="left")

    # 4. CPI year-over-year inflation
    df["cpi_yoy_inflation"] = (df["cpi"] / df["cpi"].shift(12) - 1) * 100

    # 5. Real federal funds rate
    df["real_fed_funds_rate"] = df["fedfunds"] - df["cpi_yoy_inflation"]

    # 6. Sahm Rule (compute on full UNRATE history, then merge)
    ur_full = ur_raw.dropna(subset=["value"]).copy()
    ur_full = ur_full.sort_values("date").reset_index(drop=True)
    ur_full["value"] = ur_full["value"].ffill()
    ur_full["ma3"] = ur_full["value"].rolling(3, min_periods=3).mean()
    ur_full["trail_min"] = ur_full["ma3"].shift(1).rolling(12, min_periods=12).min()
    ur_full["sahm"] = ur_full["ma3"] - ur_full["trail_min"]
    sahm_series = ur_full[["date", "sahm"]].rename(columns={"sahm": "sahm_rule_indicator"})
    df = df.merge(sahm_series, on="date", how="left")

    # 7. Real GDP, HP filter, output gap
    gdp = gdp_raw.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)
    q_cpi_list = []
    for _, row in gdp.iterrows():
        q_start = row["date"]
        q_end = q_start + pd.DateOffset(months=2)
        q_months = pd.date_range(q_start, q_end, freq="MS")
        vals = cpi_raw.loc[cpi_raw["date"].isin(q_months), "value"].dropna()
        q_cpi_list.append(vals.mean() if len(vals) > 0 else np.nan)

    gdp["q_cpi"] = q_cpi_list
    gdp["real_gdp"] = gdp["value"] * 100.0 / gdp["q_cpi"]

    valid_rgdp = gdp.dropna(subset=["real_gdp"]).reset_index(drop=True)
    log_rgdp = np.log(valid_rgdp["real_gdp"].values.astype(float))
    trend, cycle = hp_filter(log_rgdp, lamb=1600)
    valid_rgdp = valid_rgdp.copy()
    valid_rgdp["output_gap"] = cycle * 100.0

    # Interpolate output gap quarterly to monthly
    og_monthly_vals = quarterly_to_monthly_spline(
        valid_rgdp["date"].values,
        valid_rgdp["output_gap"].values,
        months,
    )
    df["output_gap"] = og_monthly_vals

    # 8. Taylor Rule
    df["taylor_rule_rate"] = (
        1.0 + 1.5 * df["cpi_yoy_inflation"] + 0.5 * df["output_gap"]
    )
    df["taylor_gap"] = df["taylor_rule_rate"] - df["fedfunds"]

    # 9. M2 velocity
    vel_dates = []
    vel_values = []
    for _, row in gdp.iterrows():
        q_start = row["date"]
        q_months = pd.date_range(q_start, q_start + pd.DateOffset(months=2), freq="MS")
        m2_vals = m2_raw.loc[m2_raw["date"].isin(q_months), "value"].dropna()
        if len(m2_vals) > 0 and not np.isnan(row["value"]):
            vel_dates.append(q_start)
            vel_values.append(float(row["value"]) / float(m2_vals.mean()))

    vel_monthly_vals = quarterly_to_monthly_spline(
        vel_dates, vel_values, months
    )
    df["m2_velocity"] = vel_monthly_vals

    # 10. Payroll momentum
    df["payroll_change"] = df["payems"].diff()
    df["payroll_momentum"] = df["payroll_change"].rolling(3, min_periods=3).mean()

    # -- Build output --------------------------------------------------------

    monthly_data = {}
    for _, row in df.iterrows():
        key = row["date"].strftime("%Y-%m")
        monthly_data[key] = {
            "cpi": safe_val(row["cpi"]),
            "cpi_yoy_inflation": safe_val(row["cpi_yoy_inflation"]),
            "fedfunds": safe_val(row["fedfunds"]),
            "real_fed_funds_rate": safe_val(row["real_fed_funds_rate"]),
            "unrate": safe_val(row["unrate"]),
            "sahm_rule_indicator": safe_val(row["sahm_rule_indicator"]),
            "m2_velocity": safe_val(row["m2_velocity"]),
            "taylor_rule_rate": safe_val(row["taylor_rule_rate"]),
            "taylor_gap": safe_val(row["taylor_gap"]),
            "t10y2y_monthly_avg": safe_val(row["t10y2y"]),
            "dgs10_monthly_avg": safe_val(row["dgs10"]),
            "payroll_momentum": safe_val(row["payroll_momentum"]),
        }

    # Yield curve inversion episodes (monthly average T10Y2Y < 0)
    inversion_episodes = []
    in_inv = False
    ep_start = None
    ep_spreads = []
    for _, row in df.iterrows():
        val = row["t10y2y"]
        dstr = row["date"].strftime("%Y-%m")
        is_neg = pd.notna(val) and not (isinstance(val, float) and math.isnan(val)) and float(val) < 0
        if is_neg:
            if not in_inv:
                in_inv = True
                ep_start = dstr
                ep_spreads = [float(val)]
            else:
                ep_spreads.append(float(val))
        else:
            if in_inv:
                prev = (row["date"] - pd.DateOffset(months=1)).strftime("%Y-%m")
                inversion_episodes.append({
                    "start_month": ep_start,
                    "end_month": prev,
                    "duration_months": len(ep_spreads),
                    "min_monthly_avg_spread": round(min(ep_spreads), 4),
                    "mean_monthly_avg_spread": round(
                        sum(ep_spreads) / len(ep_spreads), 4
                    ),
                })
                in_inv = False
    if in_inv:
        last_date = df["date"].iloc[-1].strftime("%Y-%m")
        inversion_episodes.append({
            "start_month": ep_start,
            "end_month": last_date,
            "duration_months": len(ep_spreads),
            "min_monthly_avg_spread": round(min(ep_spreads), 4),
            "mean_monthly_avg_spread": round(
                sum(ep_spreads) / len(ep_spreads), 4
            ),
        })

    # Sahm Rule trigger months
    sahm_triggers = []
    for _, row in df.iterrows():
        val = row.get("sahm_rule_indicator")
        if pd.notna(val) and float(val) >= 0.50:
            sahm_triggers.append(row["date"].strftime("%Y-%m"))

    # Summary statistics
    valid_inf = df.dropna(subset=["cpi_yoy_inflation"])
    mi_idx = valid_inf["cpi_yoy_inflation"].idxmax()
    mi_row = df.loc[mi_idx]

    valid_rr = df.dropna(subset=["real_fed_funds_rate"])
    rr_idx = valid_rr["real_fed_funds_rate"].idxmin()
    rr_row = df.loc[rr_idx]

    valid_tg = df.dropna(subset=["taylor_gap"])
    tg_idx = valid_tg["taylor_gap"].idxmax()
    tg_row = df.loc[tg_idx]

    longest = max(inversion_episodes, key=lambda e: e["duration_months"]) \
              if inversion_episodes else {"duration_months": 0}

    summary = {
        "total_months": int(len(df)),
        "max_inflation": {
            "date": mi_row["date"].strftime("%Y-%m"),
            "value": round(float(mi_row["cpi_yoy_inflation"]), 4),
        },
        "min_real_rate": {
            "date": rr_row["date"].strftime("%Y-%m"),
            "value": round(float(rr_row["real_fed_funds_rate"]), 4),
        },
        "max_taylor_gap": {
            "date": tg_row["date"].strftime("%Y-%m"),
            "value": round(float(tg_row["taylor_gap"]), 4),
        },
        "num_inversion_episodes": len(inversion_episodes),
        "num_sahm_triggers": len(sahm_triggers),
        "longest_inversion_months": int(longest["duration_months"]),
    }

    output = {
        "metadata": {
            "start_date": "1977-01",
            "end_date": "2025-12",
            "num_months": int(len(df)),
            "series_used": [
                "CPIAUCSL", "GDP", "FEDFUNDS", "UNRATE",
                "M2SL", "DGS10", "T10Y2Y", "PAYEMS",
            ],
        },
        "monthly_data": monthly_data,
        "inversion_episodes": inversion_episodes,
        "sahm_rule_triggers": sahm_triggers,
        "summary": summary,
    }

    out_path = f"{OUTPUT_DIR}/indicators.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, allow_nan=False)

    print(f"Wrote {out_path}")
    print(f"  Months:             {len(df)}")
    print(f"  Inversion episodes: {len(inversion_episodes)}")
    print(f"  Sahm triggers:      {len(sahm_triggers)}")
    print(f"  Peak inflation:     {summary['max_inflation']}")
    print(f"  Min real rate:      {summary['min_real_rate']}")
    print(f"  Max Taylor gap:     {summary['max_taylor_gap']}")
    print(f"  Longest inversion:  {summary['longest_inversion_months']} months")


if __name__ == "__main__":
    main()
