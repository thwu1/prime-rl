#!/usr/bin/env python3

"""
Solution: Conversion rate forensics with right-censored survival data.

Diagnoses the censoring bias in the dashboard, fits Weibull mixture cure
models per channel via MLE, and produces corrected metrics.
"""

import json
import csv
import sqlite3
import numpy as np
from scipy.optimize import minimize
from datetime import date

ANALYSIS_DATE = date(2024, 3, 15)
DB_PATH = "/app/data/acquisition.db"
COSTS_PATH = "/app/data/channel_costs.csv"
RESULTS_PATH = "/app/results.json"


def load_survival_data():
    """Load user data, clean it, and build per-channel survival datasets."""
    conn = sqlite3.connect(DB_PATH)

    users = {}
    for uid, signup, channel in conn.execute(
        "SELECT user_id, signup_date, channel FROM users"
    ):
        users[uid] = {"signup": signup, "channel": channel}

    # First valid conversion per user: filter bad dates, deduplicate
    conversions = {}
    for uid, conv_date in conn.execute("""
        SELECT me.user_id, MIN(me.event_date)
        FROM milestone_events me
        JOIN users u ON me.user_id = u.user_id
        WHERE me.event_type = 'conversion'
          AND me.event_date >= u.signup_date
        GROUP BY me.user_id
    """):
        conversions[uid] = conv_date

    conn.close()

    channel_data = {}
    for uid, info in users.items():
        ch = info["channel"]
        if ch not in channel_data:
            channel_data[ch] = {"durations": [], "events": []}

        signup = date.fromisoformat(info["signup"])

        if uid in conversions:
            conv = date.fromisoformat(conversions[uid])
            duration = (conv - signup).days
            duration = max(duration, 0.5)
            channel_data[ch]["durations"].append(duration)
            channel_data[ch]["events"].append(1)
        else:
            duration = (ANALYSIS_DATE - signup).days
            duration = max(duration, 0.5)
            channel_data[ch]["durations"].append(duration)
            channel_data[ch]["events"].append(0)

    return channel_data


def fit_weibull_cure(durations, events):
    """Fit Weibull mixture cure model via maximum likelihood.

    Model: F(t) = c * (1 - exp(-(t/scale)^k))
    Parameters are transformed for unconstrained optimization:
      params[0] -> c via sigmoid
      params[1] -> scale via exp
      params[2] -> k via exp
    """
    T = np.array(durations, dtype=np.float64)
    E = np.array(events, dtype=np.float64)
    log_T = np.log(T)

    def neg_ll(params):
        c = 1.0 / (1.0 + np.exp(-params[0]))
        scale = np.exp(params[1])
        k = np.exp(params[2])

        z = (T / scale) ** k
        log_f = (np.log(k) - np.log(scale)
                 + (k - 1) * (log_T - np.log(scale)) - z)
        S = np.exp(-z)

        ll_obs = E * (np.log(c + 1e-300) + log_f)
        ll_cens = (1 - E) * np.log((1 - c) + c * S + 1e-300)

        return -(np.sum(ll_obs) + np.sum(ll_cens))

    best = None
    best_nll = np.inf
    rng = np.random.RandomState(12345)

    for _ in range(30):
        x0 = [
            rng.randn() * 0.5 - 1.0,
            np.log(30) + rng.randn() * 0.5,
            rng.randn() * 0.3,
        ]
        try:
            res = minimize(
                neg_ll, x0, method="Nelder-Mead",
                options={"maxiter": 30000, "xatol": 1e-10, "fatol": 1e-10},
            )
            if res.fun < best_nll:
                best_nll = res.fun
                best = res
        except Exception:
            pass

    c = 1.0 / (1.0 + np.exp(-best.x[0]))
    scale = np.exp(best.x[1])
    k = np.exp(best.x[2])
    median = scale * np.log(2) ** (1.0 / k)

    return c, scale, k, median


def load_costs():
    costs = {}
    with open(COSTS_PATH) as f:
        reader = csv.DictReader(f)
        for row in reader:
            costs[row["channel"]] = int(row["cost_per_user_cents"]) / 100.0
    return costs


def get_naive_rates():
    conn = sqlite3.connect(DB_PATH)
    rates = {}
    for row in conn.execute(
        "SELECT channel, conversion_rate FROM dashboard_metrics"
    ):
        rates[row[0]] = row[1]
    conn.close()
    return rates


def main():
    channel_data = load_survival_data()
    costs = load_costs()
    naive_rates = get_naive_rates()

    channels_result = {}
    for ch in sorted(channel_data):
        data = channel_data[ch]
        c, scale, k, median = fit_weibull_cure(
            data["durations"], data["events"]
        )
        cost = costs.get(ch, 0)
        cpc = round(cost / c, 2) if c > 0 and cost > 0 else None

        channels_result[ch] = {
            "naive_rate": naive_rates.get(ch, 0),
            "true_rate": round(float(c), 4),
            "median_days_to_convert": round(float(median), 1),
            "cost_per_true_conversion": cpc,
        }
        print(
            f"{ch}: naive={naive_rates.get(ch, 0):.4f}, true={c:.4f}, "
            f"scale={scale:.1f}, k={k:.2f}, median={median:.1f}"
        )

    # Ranking by cost-effectiveness
    free_chs = [
        ch for ch, m in channels_result.items()
        if m["cost_per_true_conversion"] is None
    ]
    paid_chs = [
        (ch, m["cost_per_true_conversion"])
        for ch, m in channels_result.items()
        if m["cost_per_true_conversion"] is not None
    ]
    paid_chs.sort(key=lambda x: x[1])
    ranking = free_chs + [ch for ch, _ in paid_chs]

    # Budget allocation: inversely proportional to cost per conversion
    inv_costs = {ch: 1.0 / cpc for ch, cpc in paid_chs}
    total_inv = sum(inv_costs.values())
    budget = {ch: round(v / total_inv, 4) for ch, v in inv_costs.items()}

    results = {
        "methodology_flaw": (
            "The dashboard divides observed conversions by total users "
            "without accounting for right-censoring: users who signed up "
            "recently have not had sufficient observation time to convert, "
            "systematically deflating reported rates for newer cohorts and "
            "creating a false impression of declining channel performance."
        ),
        "channels": channels_result,
        "ranking": ranking,
        "budget_allocation": budget,
    }

    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults written to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
