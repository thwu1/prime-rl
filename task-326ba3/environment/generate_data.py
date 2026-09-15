#!/usr/bin/env python3
"""Generate synthetic M6-style financial competition data."""

import numpy as np
import pandas as pd
import os

def main():
    np.random.seed(42)

    N_ASSETS = 50
    N_TEAMS = 10
    N_PERIODS = 4
    DAYS_PER_PERIOD = 20

    symbols = [f"A{i:02d}" for i in range(N_ASSETS)]
    asset_classes = ["Stock"] * 30 + ["ETF"] * 20
    periods = [f"P{i+1}" for i in range(N_PERIODS)]
    team_ids = [f"T{i:02d}" for i in range(N_TEAMS)]

    total_days = N_PERIODS * DAYS_PER_PERIOD
    dates = pd.bdate_range(start="2023-01-02", periods=total_days)

    # GBM parameters per asset
    mu = np.random.uniform(-0.0003, 0.0008, N_ASSETS)
    sigma = np.random.uniform(0.012, 0.032, N_ASSETS)
    initial_prices = np.random.uniform(25, 180, N_ASSETS)

    prices_matrix = np.zeros((total_days, N_ASSETS))
    prices_matrix[0] = initial_prices

    for t in range(1, total_days):
        z = np.random.standard_normal(N_ASSETS)
        prices_matrix[t] = prices_matrix[t - 1] * np.exp(
            (mu - 0.5 * sigma ** 2) + sigma * z
        )

    prices_matrix = np.round(prices_matrix, 4)

    # Create exact ties for testing tie-handling by copying prices
    # Period 2 (days 20-39): make A09 have identical prices to A08
    # (ensuring bit-exact return equality)
    for t in range(20, 40):
        prices_matrix[t, 9] = prices_matrix[t, 8]

    # Period 3 (days 40-59): make A23, A24 have identical prices to A22
    for t in range(40, 60):
        prices_matrix[t, 23] = prices_matrix[t, 22]
        prices_matrix[t, 24] = prices_matrix[t, 22]

    # Period definitions
    period_defs = {}
    for p_idx in range(N_PERIODS):
        s = p_idx * DAYS_PER_PERIOD
        e = s + DAYS_PER_PERIOD - 1
        period_defs[periods[p_idx]] = (s, e)

    # Build prices CSV
    records = []
    for j in range(total_days):
        for i in range(N_ASSETS):
            records.append({
                "symbol": symbols[i],
                "date": dates[j].strftime("%Y-%m-%d"),
                "price": float(prices_matrix[j, i])
            })
    prices_df = pd.DataFrame(records)

    # Universe CSV
    universe_df = pd.DataFrame({
        "symbol": symbols,
        "asset_class": asset_classes
    })

    # Periods CSV
    period_rows = []
    for p_idx in range(N_PERIODS):
        s, e = period_defs[periods[p_idx]]
        period_rows.append({
            "period": periods[p_idx],
            "start_date": dates[s].strftime("%Y-%m-%d"),
            "end_date": dates[e].strftime("%Y-%m-%d")
        })
    periods_df = pd.DataFrame(period_rows)

    # Compute actual returns per period (for generating submissions)
    actual_returns_by_period = {}
    for p in periods:
        s, e = period_defs[p]
        rets = (prices_matrix[e] - prices_matrix[s]) / prices_matrix[s]
        actual_returns_by_period[p] = rets

    # Generate team submissions
    all_subs = []
    for team_idx, team_id in enumerate(team_ids):
        # Skill: lower = better. T00 is best, T09 is worst.
        skill = 0.15 + team_idx * 0.08

        for p in periods:
            rets = actual_returns_by_period[p]

            # Rank ascending (rank 1 = lowest return)
            order = np.argsort(rets)
            ranks = np.empty(N_ASSETS, dtype=int)
            ranks[order] = np.arange(1, N_ASSETS + 1)

            # Quintile: 1-10 -> Q1, 11-20 -> Q2, etc.
            quintiles = np.clip((ranks - 1) // 10 + 1, 1, 5)

            period_decisions = []

            for asset_idx in range(N_ASSETS):
                tq = quintiles[asset_idx]

                # Generate noisy quintile probabilities
                base = np.ones(5) * 0.05
                base[tq - 1] += 1.5
                noise = np.random.dirichlet(
                    np.ones(5) * (1.0 / max(0.05, skill))
                )
                probs = (1 - skill) * base / base.sum() + skill * noise
                probs = np.clip(probs, 0.001, None)
                probs = probs / probs.sum()
                probs = np.round(probs, 4)
                probs[4] = round(1.0 - float(sum(probs[:4])), 4)
                # Safety: if last prob went negative from rounding
                if probs[4] < 0.0001:
                    probs[4] = 0.0001
                    probs = probs / probs.sum()
                    probs = np.round(probs, 4)
                    probs[4] = round(1.0 - float(sum(probs[:4])), 4)

                # Investment decision: higher expected quintile -> positive weight
                expected_rank = np.dot(probs, [1, 2, 3, 4, 5])
                base_dec = (expected_rank - 3) * 0.012
                noise_dec = np.random.normal(0, skill * 0.005)
                dec = base_dec + noise_dec
                dec = float(np.clip(dec, -0.035, 0.035))
                dec = round(dec, 6)
                period_decisions.append(dec)

                all_subs.append({
                    "Team": team_id,
                    "Period": p,
                    "Symbol": symbols[asset_idx],
                    "Rank1": float(probs[0]),
                    "Rank2": float(probs[1]),
                    "Rank3": float(probs[2]),
                    "Rank4": float(probs[3]),
                    "Rank5": float(probs[4]),
                    "Decision": dec
                })

            # Normalize decisions so abs sum <= 1
            abs_sum = sum(abs(d) for d in period_decisions)
            if abs_sum > 1.0:
                start = len(all_subs) - N_ASSETS
                for k in range(N_ASSETS):
                    old = all_subs[start + k]["Decision"]
                    all_subs[start + k]["Decision"] = round(old / abs_sum, 6)

    submissions_df = pd.DataFrame(all_subs)

    # Save
    os.makedirs("/app/data", exist_ok=True)
    prices_df.to_csv("/app/data/prices.csv", index=False)
    universe_df.to_csv("/app/data/universe.csv", index=False)
    submissions_df.to_csv("/app/data/submissions.csv", index=False)
    periods_df.to_csv("/app/data/periods.csv", index=False)

    print("Data generation complete.")
    print(f"  Assets: {N_ASSETS}")
    print(f"  Teams: {N_TEAMS}")
    print(f"  Periods: {N_PERIODS}")
    print(f"  Total trading days: {total_days}")
    print(f"  Prices rows: {len(prices_df)}")
    print(f"  Submissions rows: {len(submissions_df)}")

if __name__ == "__main__":
    main()
