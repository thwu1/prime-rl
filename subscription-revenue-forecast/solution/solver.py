#!/usr/bin/env python3

"""
GlobalEd IFRS-compliant revenue forecast solver.
Reads from SQLite database, CSV data files, TOML config, IFRS framework JSON,
and Parquet hedge valuations to produce a 60-month consolidated forecast with
probability-weighted ECL provisions, hedge effectiveness testing, and NPV
discounting via bootstrapped zero-coupon yield curve.
"""

import csv
import json
import math
import sqlite3

try:
    import tomllib
except ImportError:
    import tomli as tomllib

import duckdb


def parse_rate_curves(csv_path):
    """Parse wide-format rate curves CSV into nested dicts."""
    cpi = {}
    growth = {}
    fx_spot = {}
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            country = row["country"]
            metric = row["metric"]
            for year_str in ["2024", "2025", "2026", "2027", "2028"]:
                year = int(year_str)
                val = float(row[year_str])
                if metric == "cpi_annual":
                    cpi.setdefault(country, {})[year] = val
                elif metric == "subscriber_growth_annual":
                    growth.setdefault(country, {})[year] = val
                elif metric == "fx_spot_to_usd":
                    fx_spot.setdefault(country, {})[year] = val
    return cpi, growth, fx_spot


def parse_hedge_book(csv_path):
    """Parse hedge book CSV, filtering to active contracts only."""
    hedges = {}
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["status"] != "active":
                continue
            currency = row["currency"]
            year = int(row["fiscal_year"])
            country = "AUS" if currency == "AUD" else "UK" if currency == "GBP" else None
            if country is None:
                continue
            hedges.setdefault(country, {})[year] = {
                "ratio": float(row["hedge_ratio"]),
                "forward": float(row["forward_rate"]),
                "contract_id": row["contract_id"],
            }
    return hedges


def parse_credit_provisions(csv_path):
    """Parse credit provisions CSV, filtering to approved rates only."""
    ecl = {}
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["review_status"] != "approved":
                continue
            ecl[row["tier_name"]] = float(row["expected_loss_rate"])
    return ecl


def load_ifrs_framework(json_path):
    """Load IFRS framework JSON and extract required parameters."""
    with open(json_path) as f:
        framework = json.load(f)

    # Navigate to ECL scenario parameters (current version, not superseded)
    ecl_section = framework["standards"]["ifrs9"]["chapters"]["5"]["sections"]["5.5"]
    ecl_params = ecl_section["subsections"]["5.5.15"]["parameters"]
    scenarios = ecl_params["forward_looking_assessment"]["current_v2024"]["scenarios"]

    # Navigate to hedge effectiveness bounds
    hedge_section = framework["standards"]["ifrs9"]["chapters"]["6"]["sections"]["6.4"]
    hedge_params = hedge_section["subsections"]["6.4.1"]["parameters"]
    effectiveness_bounds = hedge_params["effectiveness_bounds"]

    return {
        "ecl_scenarios": scenarios,
        "effectiveness_lower": effectiveness_bounds["lower"],
        "effectiveness_upper": effectiveness_bounds["upper"],
    }


def compute_hedge_effectiveness(parquet_path):
    """Query Parquet file with DuckDB to compute dollar-offset ratios per contract."""
    conn = duckdb.connect()
    result = conn.execute("""
        SELECT
            contract_id,
            ABS(SUM(hedge_instrument_pnl) / SUM(hedged_item_pnl)) AS dollar_offset_ratio
        FROM read_parquet(?)
        GROUP BY contract_id
        ORDER BY contract_id
    """, [parquet_path]).fetchall()
    conn.close()
    return {row[0]: row[1] for row in result}


def bootstrap_zero_rates(par_rates):
    """Bootstrap zero-coupon rates from par bond rates using iterative method.

    For tenor n=1: z_1 = par_rate (trivial case).
    For tenor n>1: solve 100 = SUM(C/(1+z_k)^k, k=1..n-1) + (100+C)/(1+z_n)^n
    where C = par_rate * 100.
    """
    zero_rates = {}
    for n in sorted(par_rates.keys()):
        c = par_rates[n]  # annual coupon rate as fraction
        if n == 1:
            zero_rates[n] = c
        else:
            pv_coupons = sum(100.0 * c / (1 + zero_rates[k]) ** k for k in range(1, n))
            remaining = 100.0 - pv_coupons
            face_plus_coupon = 100.0 + 100.0 * c
            zero_rates[n] = (face_plus_coupon / remaining) ** (1.0 / n) - 1
    return zero_rates


def solve():
    db_path = "/app/model.db"
    config_path = "/app/config/policy.toml"
    rate_curves_path = "/app/data/rate_curves.csv"
    hedge_path = "/app/data/hedge_book.csv"
    credit_path = "/app/data/credit_provisions.csv"
    ifrs_path = "/app/config/ifrs_framework.json"
    parquet_path = "/app/data/hedge_valuations.parquet"
    output_path = "/app/results.json"

    # Load TOML config
    with open(config_path, "rb") as f:
        config = tomllib.load(f)

    # Parse CSV data files
    cpi, growth_rates, fx_spot = parse_rate_curves(rate_curves_path)
    hedges = parse_hedge_book(hedge_path)
    ecl_base_rates = parse_credit_provisions(credit_path)

    # Load IFRS framework parameters
    ifrs = load_ifrs_framework(ifrs_path)

    # Compute hedge effectiveness from Parquet data
    dollar_offset_ratios = compute_hedge_effectiveness(parquet_path)

    # Determine which hedges pass the effectiveness test
    eff_lower = ifrs["effectiveness_lower"]
    eff_upper = ifrs["effectiveness_upper"]
    hedge_effective = {}
    effective_count = 0
    for c in ["AUS", "UK"]:
        hedge_effective[c] = {}
        for y in range(2024, 2029):
            h = hedges[c][y]
            cid = h["contract_id"]
            ratio = dollar_offset_ratios.get(cid, 0.0)
            is_eff = eff_lower <= ratio <= eff_upper
            hedge_effective[c][y] = is_eff
            if is_eff:
                effective_count += 1

    # Compute probability-weighted ECL multiplier from scenario parameters
    ecl_multiplier = sum(
        s["weight"] * s["ecl_multiplier"] for s in ifrs["ecl_scenarios"]
    )
    weighted_ecl = {t: rate * ecl_multiplier for t, rate in ecl_base_rates.items()}

    # Connect to database for entity reference data
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT code, currency FROM countries")
    countries_info = {row["code"]: row["currency"] for row in cur.fetchall()}
    COUNTRIES = list(countries_info.keys())

    cur.execute("SELECT name FROM subscription_tiers ORDER BY tier_order")
    TIERS = [row["name"] for row in cur.fetchall()]

    # Get base pricing at forecast start date
    opening_date = config["forecast"]["opening_balance_date"]
    starting_prices = {}
    for c in COUNTRIES:
        starting_prices[c] = {}
        for t in TIERS:
            cur.execute(
                "SELECT bp.monthly_price FROM base_pricing bp "
                "JOIN subscription_tiers st ON bp.tier_id = st.tier_id "
                "WHERE bp.country_code = ? AND st.name = ? "
                "AND bp.effective_date = ?",
                (c, t, opening_date),
            )
            starting_prices[c][t] = cur.fetchone()["monthly_price"]

    # Get opening subscriber counts
    starting_subs = {}
    for c in COUNTRIES:
        starting_subs[c] = {}
        for t in TIERS:
            cur.execute(
                "SELECT ss.subscriber_count FROM subscriber_snapshots ss "
                "JOIN subscription_tiers st ON ss.tier_id = st.tier_id "
                "WHERE ss.country_code = ? AND st.name = ? "
                "AND ss.snapshot_date = ?",
                (c, t, opening_date),
            )
            starting_subs[c][t] = float(cur.fetchone()["subscriber_count"])

    # Load par bond rates for yield curve bootstrapping
    cur.execute("SELECT tenor_years, par_coupon_rate FROM par_bond_rates ORDER BY tenor_years")
    par_rates = {row["tenor_years"]: row["par_coupon_rate"] for row in cur.fetchall()}

    conn.close()

    # Bootstrap zero-coupon yield curve
    zero_rates = bootstrap_zero_rates(par_rates)

    # Extract policy parameters from TOML config
    INCREMENT = config["pricing"]["adjustment"]["increment_local_currency"]
    CONSENSUS = config["pricing"]["consensus_trigger"]["consensus_threshold"]
    QUALIFYING_FRAC = config["pricing"]["consensus_trigger"]["qualifying_fraction"]
    TAX_RATES = dict(config["revenue"]["tax"]["rates"])
    TIER_MODIFIERS = dict(config["growth"]["tier_modifiers"])
    MONTHS = config["forecast"]["total_months"]
    START_YEAR = config["forecast"]["base_year"]

    def get_year(month_idx):
        return START_YEAR + month_idx // 12

    # Ensure USA has spot rate = 1.0
    for year in range(2024, 2029):
        fx_spot.setdefault("USA", {})[year] = 1.0

    # Compute monthly discount factors from bootstrapped yield curve
    discount_factors = []
    for m in range(MONTHS):
        t = (m + 1) / 12.0  # time in years (1-indexed month)
        year_bucket = max(1, min(5, int(math.ceil(t))))
        z = zero_rates[year_bucket]
        df = 1.0 / (1 + z) ** t
        discount_factors.append(df)

    # Initialize simulation state
    theoretical = {c: {t: starting_prices[c][t] for t in TIERS} for c in COUNTRIES}
    charged = {c: {t: starting_prices[c][t] for t in TIERS} for c in COUNTRIES}
    subscribers = {c: {t: starting_subs[c][t] for t in TIERS} for c in COUNTRIES}

    monthly_revenues = []
    first_price_change = {c: None for c in COUNTRIES}
    charged_history = {}
    cumulative_ecl_usd = 0.0
    cumulative_hedge_gain = 0.0

    for m in range(MONTHS):
        year = get_year(m)

        # Step 1: Update theoretical prices with monthly CPI (skip first month)
        if m > 0:
            for c in COUNTRIES:
                monthly_inf = cpi[c][year] / 12.0
                for t in TIERS:
                    theoretical[c][t] *= 1 + monthly_inf

        # Step 2: Evaluate consensus pricing trigger
        for c in COUNTRIES:
            qualifying = []
            for t in TIERS:
                threshold = charged[c][t] + INCREMENT * QUALIFYING_FRAC
                if theoretical[c][t] >= threshold:
                    qualifying.append(t)
            if len(qualifying) >= CONSENSUS:
                for t in qualifying:
                    charged[c][t] += INCREMENT
                if first_price_change[c] is None:
                    first_price_change[c] = m + 1  # 1-indexed

        # Step 3: Apply subscriber growth (skip first month)
        if m > 0:
            for c in COUNTRIES:
                for t in TIERS:
                    modified_annual = growth_rates[c][year] * TIER_MODIFIERS[t]
                    monthly_growth = (1 + modified_annual) ** (1.0 / 12.0) - 1
                    subscribers[c][t] *= 1 + monthly_growth

        # Step 4: Revenue waterfall — Gross -> Tax -> ECL (weighted) -> FX (with effectiveness)
        total_revenue_usd = 0.0
        period_ecl_usd = 0.0
        period_hedge_gain = 0.0

        for c in COUNTRIES:
            for t in TIERS:
                # 4a. Gross local revenue
                gross_local = charged[c][t] * subscribers[c][t]

                # 4b. Tax adjustment
                net_local = gross_local / (1 + TAX_RATES[c])

                # 4c. ECL provision using probability-weighted rate
                ecl_local = net_local * weighted_ecl[t]
                net_after_ecl = net_local - ecl_local

                # 4d. FX conversion with hedging (only if hedge is effective)
                if c == "USA":
                    net_usd = net_after_ecl
                    ecl_usd = ecl_local
                else:
                    spot = fx_spot[c][year]
                    h = hedges[c][year]

                    if hedge_effective.get(c, {}).get(year, False):
                        # Hedge accounting treatment (effective hedge)
                        hedge_ratio = h["ratio"]
                        forward = h["forward"]
                        hedged_usd = net_after_ecl * hedge_ratio * forward
                        unhedged_usd = net_after_ecl * (1 - hedge_ratio) * spot
                        net_usd = hedged_usd + unhedged_usd

                        effective_rate = hedge_ratio * forward + (1 - hedge_ratio) * spot
                        ecl_usd = ecl_local * effective_rate

                        hedge_gain = net_after_ecl * hedge_ratio * (forward - spot)
                        period_hedge_gain += hedge_gain
                    else:
                        # Dedesignated hedge — fair value through P&L (spot only)
                        net_usd = net_after_ecl * spot
                        ecl_usd = ecl_local * spot

                total_revenue_usd += net_usd
                period_ecl_usd += ecl_usd

        monthly_revenues.append(total_revenue_usd)
        cumulative_ecl_usd += period_ecl_usd
        cumulative_hedge_gain += period_hedge_gain
        charged_history[m + 1] = {
            c: {t: charged[c][t] for t in TIERS} for c in COUNTRIES
        }

    # Compile output metrics
    cumulative_rev = sum(monthly_revenues)
    total_subs = sum(subscribers[c][t] for c in COUNTRIES for t in TIERS)

    # NPV using bootstrapped discount factors
    npv = sum(rev * df for rev, df in zip(monthly_revenues, discount_factors))

    # AUS effective FX rate for 2026
    aus_h = hedges["AUS"][2026]
    if hedge_effective.get("AUS", {}).get(2026, False):
        aus_eff_2026 = aus_h["ratio"] * aus_h["forward"] + (1 - aus_h["ratio"]) * fx_spot["AUS"][2026]
    else:
        aus_eff_2026 = fx_spot["AUS"][2026]

    # Weighted average ECL rate across all tiers
    weighted_avg_ecl = sum(weighted_ecl[t] for t in TIERS) / len(TIERS)

    results = {
        "net_revenue_month_1": round(monthly_revenues[0], 2),
        "net_revenue_month_12": round(monthly_revenues[11], 2),
        "net_revenue_month_24": round(monthly_revenues[23], 2),
        "net_revenue_month_36": round(monthly_revenues[35], 2),
        "net_revenue_month_48": round(monthly_revenues[47], 2),
        "net_revenue_month_60": round(monthly_revenues[59], 2),
        "cumulative_net_revenue": round(cumulative_rev, 2),
        "first_price_change_month_usa": first_price_change["USA"],
        "first_price_change_month_aus": first_price_change["AUS"],
        "first_price_change_month_uk": first_price_change["UK"],
        "total_subscribers_month_60": round(total_subs),
        "usa_professional_charged_price_month_36": round(
            charged_history[36]["USA"]["Professional"], 2
        ),
        "cumulative_ecl_provision_usd": round(cumulative_ecl_usd, 2),
        "cumulative_hedge_gain_usd": round(cumulative_hedge_gain, 2),
        "aus_effective_fx_rate_2026": round(aus_eff_2026, 4),
        "npv_cumulative_revenue": round(npv, 2),
        "effective_hedge_count": effective_count,
        "weighted_avg_ecl_rate": round(weighted_avg_ecl, 6),
    }

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    solve()
