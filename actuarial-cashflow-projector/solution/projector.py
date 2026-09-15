#!/usr/bin/env python3
"""
Universal Life Insurance Cashflow Projector
Standalone reimplementation of CashValue_ME reference model.
"""


import json
import os
import sqlite3
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

DATA_DIR = "/app/data"
OUT_DIR = "/app/output"

# ── Load Data ────────────────────────────────────────────────────────────

model_point_table = pd.read_csv(f"{DATA_DIR}/model_points.csv", index_col="point_id")
product_spec_table = pd.read_csv(f"{DATA_DIR}/product_spec.csv", index_col="spec_id")
mort_table_raw = pd.read_csv(f"{DATA_DIR}/mort_table.csv", index_col="Age")
mort_table_raw.columns = [str(c) for c in mort_table_raw.columns]
disc_rate_ann_series = pd.read_csv(f"{DATA_DIR}/disc_rate_ann.csv", index_col="year")[
    "disc_rate_ann"
]
surr_charge_table = pd.read_csv(
    f"{DATA_DIR}/surr_charge_table.csv", index_col="duration"
)
inv_return_series = pd.read_csv(f"{DATA_DIR}/inv_return.csv", index_col="t")[
    "inv_return_mth"
]

# ── Prepare data ─────────────────────────────────────────────────────────

product_spec_table["has_surr_charge"] = product_spec_table["has_surr_charge"].map(
    {"True": True, "False": False, True: True, False: False}
)
product_spec_table["is_wl"] = product_spec_table["is_wl"].map(
    {"True": True, "False": False, True: True, False: False}
)

mp = model_point_table.join(product_spec_table, on="spec_id")

n_points = len(mp)
point_ids = mp.index.values
age_at_entry = mp["age_at_entry"].values
sum_assured = mp["sum_assured"].values.astype(float)
premium_pp_base = mp["premium_pp"].values.astype(float)
av_pp_init = mp["av_pp_init"].values.astype(float)
policy_count = mp["policy_count"].values.astype(float)
load_prem_rate = mp["load_prem_rate"].values.astype(float)
has_surr_charge = mp["has_surr_charge"].values
surr_charge_id_arr = mp["surr_charge_id"].values
is_wl = mp["is_wl"].values
premium_type = mp["premium_type"].values
duration_mth_0 = mp["duration_mth"].values.astype(int)

# ── Surrender charge stacked ─────────────────────────────────────────────

surr_charge_stacked = surr_charge_table.stack().reorder_levels([1, 0]).sort_index()
surr_charge_max_idx = int(surr_charge_table.index.max())

# ── Pre-compute discount and investment arrays ───────────────────────────


def get_disc_rate_mth(max_len):
    rates = np.zeros(max_len)
    for t in range(max_len):
        y = t // 12
        if y < len(disc_rate_ann_series):
            rates[t] = (1 + disc_rate_ann_series.iloc[y]) ** (1 / 12) - 1
        else:
            rates[t] = (1 + disc_rate_ann_series.iloc[-1]) ** (1 / 12) - 1
    return rates


def get_disc_factors(max_len):
    rmth = get_disc_rate_mth(max_len)
    return np.array([(1 + rmth[t]) ** (-t) for t in range(max_len)])


def get_inv_return(max_len):
    inv = np.zeros(max_len)
    for t in range(max_len):
        if t < len(inv_return_series):
            inv[t] = inv_return_series.iloc[t]
        else:
            inv[t] = inv_return_series.iloc[-1]
    return inv


# ── Projection function ─────────────────────────────────────────────────


def run_projection(mort_table, lapse_multiplier=1.0):
    """Run the full projection with the given mortality table and lapse multiplier.

    Returns dict with pv_df, checks, and timeseries arrays.
    """
    mort_table_cols = [str(c) for c in mort_table.columns]

    # Mortality table last age
    mort_table_last_age = None
    for age_val in mort_table.index:
        if (mort_table.loc[age_val] == 1.0).all():
            mort_table_last_age = age_val
            break
    if mort_table_last_age is None:
        mort_table_last_age = mort_table.index[-1]

    # Reindex mortality for vectorized lookup
    result_parts = []
    for col in mort_table.columns:
        df = mort_table[[col]].copy()
        df = df.assign(Duration=int(col)).set_index("Duration", append=True)[col]
        result_parts.append(df)
    mort_reindexed = pd.concat(result_parts)

    # Policy term
    policy_term = np.where(
        is_wl, mort_table_last_age - age_at_entry, mp["policy_term"].values
    ).astype(int)

    # Projection lengths
    proj_len = np.maximum(12 * policy_term - duration_mth_0 + 1, 0)
    max_proj_len = int(np.max(proj_len))

    disc_factors = get_disc_factors(max_proj_len)
    inv_return_arr = get_inv_return(max_proj_len)

    def mort_rate_at(age_arr, dur_arr):
        dur_capped = np.minimum(dur_arr, 5).astype(int)
        mi = pd.MultiIndex.from_arrays([age_arr, dur_capped])
        return mort_reindexed.reindex(mi, fill_value=0).values

    def surr_charge_rate_at(dur_arr):
        rates = np.zeros(n_points)
        for i in range(n_points):
            if has_surr_charge[i]:
                sc_id = surr_charge_id_arr[i]
                dur_capped = min(int(dur_arr[i]), surr_charge_max_idx)
                try:
                    rates[i] = surr_charge_stacked.loc[(sc_id, dur_capped)]
                except KeyError:
                    rates[i] = 0.0
        return rates

    # Storage arrays
    av_pp_bef_prem = np.zeros((max_proj_len, n_points))
    av_pp_bef_fee = np.zeros((max_proj_len, n_points))
    av_pp_bef_inv = np.zeros((max_proj_len, n_points))
    av_pp_mid_mth = np.zeros((max_proj_len, n_points))
    inv_income_pp_arr = np.zeros((max_proj_len, n_points))

    pols_bef_mat = np.zeros((max_proj_len + 1, n_points))
    pols_bef_nb = np.zeros((max_proj_len, n_points))
    pols_bef_decr = np.zeros((max_proj_len, n_points))
    pols_death_arr = np.zeros((max_proj_len, n_points))
    pols_lapse_arr = np.zeros((max_proj_len, n_points))
    pols_maturity_arr = np.zeros((max_proj_len, n_points))
    pols_new_biz_arr = np.zeros((max_proj_len, n_points))

    premiums_arr = np.zeros((max_proj_len, n_points))
    claims_death_arr = np.zeros((max_proj_len, n_points))
    claims_lapse_arr = np.zeros((max_proj_len, n_points))
    claims_maturity_arr = np.zeros((max_proj_len, n_points))
    claims_from_av_death = np.zeros((max_proj_len, n_points))
    claims_from_av_lapse = np.zeros((max_proj_len, n_points))
    claims_from_av_maturity = np.zeros((max_proj_len, n_points))
    expenses_arr = np.zeros((max_proj_len, n_points))
    commissions_arr = np.zeros((max_proj_len, n_points))
    inv_income_arr = np.zeros((max_proj_len, n_points))
    prem_to_av_arr = np.zeros((max_proj_len, n_points))
    maint_fee_arr = np.zeros((max_proj_len, n_points))
    coi_arr = np.zeros((max_proj_len, n_points))
    surr_charge_arr = np.zeros((max_proj_len, n_points))
    net_cf_arr = np.zeros((max_proj_len, n_points))

    av_agg_bef_mat = np.zeros((max_proj_len + 1, n_points))

    # Initialize
    pols_if_init = np.where(duration_mth_0 > 0, policy_count, 0.0)
    pols_bef_mat[0] = pols_if_init

    # Projection loop
    for t in range(max_proj_len):
        dur_mth = duration_mth_0 + t
        dur_yr = dur_mth // 12
        cur_age = age_at_entry + dur_yr

        # Policy flow
        pols_maturity_arr[t] = np.where(
            dur_mth == 12 * policy_term, pols_bef_mat[t], 0.0
        )
        pols_bef_nb[t] = pols_bef_mat[t] - pols_maturity_arr[t]
        pols_new_biz_arr[t] = np.where(dur_mth == 0, policy_count, 0.0)
        pols_bef_decr[t] = pols_bef_nb[t] + pols_new_biz_arr[t]

        # Per-policy AV
        if t == 0:
            av_pp_bef_prem[t] = av_pp_init
        else:
            av_pp_bef_prem[t] = av_pp_bef_inv[t - 1] + inv_income_pp_arr[t - 1]

        # Premium
        is_single = premium_type == "SINGLE"
        is_level = premium_type == "LEVEL"
        prem_pp_t = np.where(
            is_single & (dur_mth == 0),
            premium_pp_base,
            np.where(
                is_level & (dur_mth >= 0) & (dur_mth < 12 * policy_term),
                premium_pp_base,
                0.0,
            ),
        )
        prem_to_av_pp = (1 - load_prem_rate) * prem_pp_t

        av_pp_bef_fee[t] = av_pp_bef_prem[t] + prem_to_av_pp

        # Maintenance fee
        maint_fee_rate = 0.01 / 12
        maint_fee_pp = maint_fee_rate * av_pp_bef_fee[t]

        # COI
        mort_rate_annual = mort_rate_at(cur_age, np.minimum(dur_yr, 5))
        mort_rate_monthly = 1 - (1 - mort_rate_annual) ** (1 / 12)
        coi_rate = 1.1 * mort_rate_monthly
        net_amt_at_risk = np.maximum(sum_assured - av_pp_bef_fee[t], 0.0)
        coi_pp = coi_rate * net_amt_at_risk

        av_pp_bef_inv[t] = av_pp_bef_fee[t] - maint_fee_pp - coi_pp

        # Investment income
        inv_ret = inv_return_arr[t]
        inv_income_pp_arr[t] = inv_ret * av_pp_bef_inv[t]
        av_pp_mid_mth[t] = av_pp_bef_inv[t] + 0.5 * inv_income_pp_arr[t]

        # Decrements
        pols_death_arr[t] = pols_bef_decr[t] * mort_rate_monthly

        # Lapse rate with multiplier and cap
        lapse_rate_annual = np.minimum(
            lapse_multiplier * np.maximum(0.1 - 0.02 * dur_yr, 0.02),
            1.0,
        )
        lapse_rate_monthly = 1 - (1 - lapse_rate_annual) ** (1 / 12)
        pols_lapse_arr[t] = (
            (pols_bef_decr[t] - pols_death_arr[t]) * lapse_rate_monthly
        )

        # Claims
        claim_pp_death = np.maximum(sum_assured, av_pp_mid_mth[t])
        claims_death_arr[t] = claim_pp_death * pols_death_arr[t]
        claims_from_av_death[t] = av_pp_mid_mth[t] * pols_death_arr[t]

        claims_from_av_lapse[t] = av_pp_mid_mth[t] * pols_lapse_arr[t]
        sc_rate = surr_charge_rate_at(dur_yr)
        surr_charge_arr[t] = sc_rate * av_pp_mid_mth[t] * pols_lapse_arr[t]
        claims_lapse_arr[t] = claims_from_av_lapse[t] - surr_charge_arr[t]

        claim_pp_maturity = av_pp_bef_prem[t]
        claims_maturity_arr[t] = claim_pp_maturity * pols_maturity_arr[t]
        claims_from_av_maturity[t] = claims_maturity_arr[t]

        # Aggregate cashflows
        premiums_arr[t] = prem_pp_t * pols_bef_decr[t]
        prem_to_av_arr[t] = prem_to_av_pp * pols_bef_decr[t]
        maint_fee_arr[t] = maint_fee_pp * pols_bef_decr[t]
        coi_arr[t] = coi_pp * pols_bef_decr[t]

        inv_income_arr[t] = inv_income_pp_arr[t] * (
            pols_bef_decr[t] - pols_death_arr[t] - pols_lapse_arr[t]
        ) + 0.5 * inv_income_pp_arr[t] * (pols_death_arr[t] + pols_lapse_arr[t])

        inflation_factor = (1.01) ** (t / 12)
        expenses_arr[t] = (
            5000.0 * pols_new_biz_arr[t]
            + pols_bef_decr[t] * (500.0 / 12) * inflation_factor
        )
        commissions_arr[t] = 0.05 * premiums_arr[t]

        av_agg_bef_mat[t] = av_pp_bef_prem[t] * pols_bef_mat[t]

        # Next period
        pols_bef_mat[t + 1] = (
            pols_bef_decr[t] - pols_death_arr[t] - pols_lapse_arr[t]
        )

    # Final aggregate AV
    if max_proj_len > 0:
        av_agg_bef_mat[max_proj_len] = (
            (av_pp_bef_inv[max_proj_len - 1] + inv_income_pp_arr[max_proj_len - 1])
            * pols_bef_mat[max_proj_len]
        )

    # AV change and net CF
    av_change_arr = np.zeros((max_proj_len, n_points))
    for t in range(max_proj_len):
        av_change_arr[t] = av_agg_bef_mat[t + 1] - av_agg_bef_mat[t]

    total_claims = claims_death_arr + claims_lapse_arr + claims_maturity_arr
    net_cf_arr = (
        premiums_arr
        + inv_income_arr
        - total_claims
        - expenses_arr
        - commissions_arr
        - av_change_arr
    )

    # Present values
    df = disc_factors[:max_proj_len]
    pv_premiums = premiums_arr.T @ df
    pv_claims_death = claims_death_arr.T @ df
    pv_claims_lapse = claims_lapse_arr.T @ df
    pv_claims_maturity = claims_maturity_arr.T @ df
    pv_expenses = expenses_arr.T @ df
    pv_commissions = commissions_arr.T @ df
    pv_inv_income = inv_income_arr.T @ df
    pv_av_change = av_change_arr.T @ df
    pv_net_cf = net_cf_arr.T @ df

    # Self-consistency checks
    av_roll_forward_ok = True
    for t in range(max_proj_len):
        expected_next = (
            av_agg_bef_mat[t]
            + prem_to_av_arr[t]
            - maint_fee_arr[t]
            - coi_arr[t]
            + inv_income_arr[t]
            - claims_from_av_death[t]
            - claims_from_av_lapse[t]
            - claims_from_av_maturity[t]
        )
        if not np.allclose(
            expected_next, av_agg_bef_mat[t + 1], rtol=1e-6, atol=1e-10
        ):
            av_roll_forward_ok = False
            break

    margin_ok = True
    for t in range(max_proj_len):
        premium_loading_t = premiums_arr[t] - prem_to_av_arr[t]
        expense_margin = (
            premium_loading_t
            + surr_charge_arr[t]
            + maint_fee_arr[t]
            - commissions_arr[t]
            - expenses_arr[t]
        )
        claims_over_av_death = claims_death_arr[t] - claims_from_av_death[t]
        mortality_margin = coi_arr[t] - claims_over_av_death
        expected_net_cf = expense_margin + mortality_margin
        if not np.allclose(net_cf_arr[t], expected_net_cf, rtol=1e-6, atol=1e-10):
            margin_ok = False
            break

    pv_computed = (
        pv_premiums
        + pv_inv_income
        - pv_claims_death
        - pv_claims_lapse
        - pv_claims_maturity
        - pv_expenses
        - pv_commissions
        - pv_av_change
    )
    pv_ok = bool(np.allclose(pv_net_cf, pv_computed, rtol=1e-6, atol=1e-10))

    # Build PV DataFrame
    pv_df = pd.DataFrame(
        {
            "point_id": point_ids,
            "pv_premiums": pv_premiums,
            "pv_claims_death": pv_claims_death,
            "pv_claims_lapse": pv_claims_lapse,
            "pv_claims_maturity": pv_claims_maturity,
            "pv_expenses": pv_expenses,
            "pv_commissions": pv_commissions,
            "pv_inv_income": pv_inv_income,
            "pv_av_change": pv_av_change,
            "pv_net_cf": pv_net_cf,
        }
    )

    checks = {
        "av_roll_forward_ok": bool(av_roll_forward_ok),
        "margin_ok": bool(margin_ok),
        "pv_ok": bool(pv_ok),
    }

    return {
        "pv_df": pv_df,
        "checks": checks,
        "premiums": premiums_arr,
        "claims_death": claims_death_arr,
        "claims_lapse": claims_lapse_arr,
        "claims_maturity": claims_maturity_arr,
        "expenses": expenses_arr,
        "commissions": commissions_arr,
        "inv_income": inv_income_arr,
        "net_cf": net_cf_arr,
        "pols_bef_decr": pols_bef_decr,
        "av_pp_bef_prem": av_pp_bef_prem,
        "max_proj_len": max_proj_len,
    }


# ── Main ─────────────────────────────────────────────────────────────────

os.makedirs(OUT_DIR, exist_ok=True)

# ── Base projection ──────────────────────────────────────────────────────

print("Running base projection...")
base = run_projection(mort_table_raw, lapse_multiplier=1.0)

# Write pv_results.csv
base["pv_df"].to_csv(f"{OUT_DIR}/pv_results.csv", index=False)

# Write checks.json
with open(f"{OUT_DIR}/checks.json", "w") as f:
    json.dump(base["checks"], f, indent=2)

# Write timeseries.db
print("Writing SQLite time-series database...")
mpl = base["max_proj_len"]
t_idx = np.repeat(np.arange(mpl), n_points)
pid_idx = np.tile(point_ids, mpl)

ts_df = pd.DataFrame(
    {
        "t": t_idx.astype(int),
        "point_id": pid_idx.astype(int),
        "premiums": base["premiums"].flatten(),
        "claims_death": base["claims_death"].flatten(),
        "claims_lapse": base["claims_lapse"].flatten(),
        "claims_maturity": base["claims_maturity"].flatten(),
        "expenses": base["expenses"].flatten(),
        "commissions": base["commissions"].flatten(),
        "inv_income": base["inv_income"].flatten(),
        "net_cf": base["net_cf"].flatten(),
        "pols_if": base["pols_bef_decr"].flatten(),
        "av_pp": base["av_pp_bef_prem"].flatten(),
    }
)

conn = sqlite3.connect(f"{OUT_DIR}/timeseries.db")
cursor = conn.cursor()
cursor.execute(
    """CREATE TABLE IF NOT EXISTS monthly_cf (
        t INTEGER,
        point_id INTEGER,
        premiums REAL,
        claims_death REAL,
        claims_lapse REAL,
        claims_maturity REAL,
        expenses REAL,
        commissions REAL,
        inv_income REAL,
        net_cf REAL,
        pols_if REAL,
        av_pp REAL,
        PRIMARY KEY (t, point_id)
    )"""
)

ts_df.to_sql("monthly_cf", conn, if_exists="replace", index=False)

# Create index
cursor.execute(
    "CREATE INDEX IF NOT EXISTS idx_monthly_cf_point_t "
    "ON monthly_cf(point_id, t)"
)

# Create cumulative view
cursor.execute(
    """CREATE VIEW IF NOT EXISTS cumulative_cf AS
    SELECT
        t,
        point_id,
        SUM(premiums) OVER (PARTITION BY point_id ORDER BY t
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cum_premiums,
        SUM(net_cf) OVER (PARTITION BY point_id ORDER BY t
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cum_net_cf,
        SUM(claims_death) OVER (PARTITION BY point_id ORDER BY t
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cum_claims_death
    FROM monthly_cf"""
)

conn.commit()
conn.close()

# Write timeseries.parquet
print("Writing Parquet time-series file...")
parquet_schema = pa.schema(
    [
        ("t", pa.int32()),
        ("point_id", pa.int32()),
        ("premiums", pa.float64()),
        ("claims_death", pa.float64()),
        ("claims_lapse", pa.float64()),
        ("claims_maturity", pa.float64()),
        ("expenses", pa.float64()),
        ("commissions", pa.float64()),
        ("inv_income", pa.float64()),
        ("net_cf", pa.float64()),
        ("pols_if", pa.float64()),
        ("av_pp", pa.float64()),
    ]
)

# Build pyarrow table with explicit schema
table = pa.table(
    {
        "t": pa.array(ts_df["t"].values, type=pa.int32()),
        "point_id": pa.array(ts_df["point_id"].values, type=pa.int32()),
        "premiums": pa.array(ts_df["premiums"].values, type=pa.float64()),
        "claims_death": pa.array(ts_df["claims_death"].values, type=pa.float64()),
        "claims_lapse": pa.array(ts_df["claims_lapse"].values, type=pa.float64()),
        "claims_maturity": pa.array(
            ts_df["claims_maturity"].values, type=pa.float64()
        ),
        "expenses": pa.array(ts_df["expenses"].values, type=pa.float64()),
        "commissions": pa.array(ts_df["commissions"].values, type=pa.float64()),
        "inv_income": pa.array(ts_df["inv_income"].values, type=pa.float64()),
        "net_cf": pa.array(ts_df["net_cf"].values, type=pa.float64()),
        "pols_if": pa.array(ts_df["pols_if"].values, type=pa.float64()),
        "av_pp": pa.array(ts_df["av_pp"].values, type=pa.float64()),
    },
    schema=parquet_schema,
)
pq.write_table(table, f"{OUT_DIR}/timeseries.parquet", compression="snappy")

# ── Mortality stress projection ─────────────────────────────────────────

print("Running mortality stress projection (mortality x1.3)...")
stress_mort = mort_table_raw.copy() * 1.3
stress_mort = stress_mort.clip(upper=1.0)
stress_mort_result = run_projection(stress_mort, lapse_multiplier=1.0)

stress_mort_result["pv_df"].to_csv(f"{OUT_DIR}/stress_mort_pv.csv", index=False)

# ── Lapse stress projection ─────────────────────────────────────────────

print("Running lapse stress projection (lapse x2.0)...")
stress_lapse_result = run_projection(mort_table_raw, lapse_multiplier=2.0)

stress_lapse_result["pv_df"].to_csv(f"{OUT_DIR}/stress_lapse_pv.csv", index=False)

# ── Summary ──────────────────────────────────────────────────────────────

print("Projection complete.")
print(f"  Model points: {n_points}")
print(f"  Max projection length: {mpl} months")
print(f"  AV roll-forward check: {'PASS' if base['checks']['av_roll_forward_ok'] else 'FAIL'}")
print(f"  Margin decomposition check: {'PASS' if base['checks']['margin_ok'] else 'FAIL'}")
print(f"  PV consistency check: {'PASS' if base['checks']['pv_ok'] else 'FAIL'}")
print(f"  SQLite rows written: {len(ts_df)}")
print(f"  Parquet rows written: {len(table)}")
print(f"  Mortality stress: complete")
print(f"  Lapse stress: complete")
