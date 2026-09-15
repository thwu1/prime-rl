#!/usr/bin/env python3

"""
Reference solution: probabilistic CLV from raw transaction data.

1. Cleans transaction data (remove refunds, deduplicate)
2. Computes RFM summary per customer
3. Fits BG/NBD model for purchase frequency via MLE
4. Fits Gamma-Gamma model for monetary value via MLE
5. Computes per-customer P(alive), conditional expected purchases,
   predicted monetary value, and CLV
"""

import csv
import json
import os
from datetime import datetime
import numpy as np
from scipy.special import gammaln, betaln, hyp2f1
from scipy.optimize import minimize


# ===================================================================
# Data loading and RFM computation
# ===================================================================

def load_and_clean_transactions(path, config_path):
    with open(config_path) as f:
        config = json.load(f)
    obs_end = datetime.strptime(config["observation_end"], "%Y-%m-%d")

    seen_ids = set()
    by_customer = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            tid = int(row["transaction_id"])
            if tid in seen_ids:
                continue
            seen_ids.add(tid)
            amt = float(row["amount"])
            if amt < 0:
                continue
            cid = int(row["customer_id"])
            dt = datetime.strptime(row["date"], "%Y-%m-%d")
            by_customer.setdefault(cid, []).append((dt, amt, tid))

    customers = []
    for cid in sorted(by_customer):
        purchases = sorted(by_customer[cid], key=lambda x: (x[0], x[2]))
        first_date = purchases[0][0]
        last_date = purchases[-1][0]
        n = len(purchases)
        freq = n - 1
        rec = (last_date - first_date).days / 7.0
        t_obs = (obs_end - first_date).days / 7.0
        if freq > 0:
            mon = sum(p[1] for p in purchases[1:]) / freq
        else:
            mon = 0.0
        customers.append({
            "customer_id": cid,
            "frequency": freq,
            "recency": rec,
            "T": t_obs,
            "monetary_value": mon,
        })

    return customers, config


# ===================================================================
# BG/NBD model
# ===================================================================

def _bgnbd_nll(log_params, frequency, recency, T):
    r, alpha, a, b = np.exp(log_params)
    x = frequency
    t_x = recency

    ln_A1 = (
        gammaln(r + x) - gammaln(r)
        + r * np.log(alpha)
        + betaln(a, b + x) - betaln(a, b)
        - (r + x) * np.log(alpha + T)
    )

    x_safe = np.maximum(x, 1.0)
    ln_A2_raw = (
        gammaln(r + x_safe) - gammaln(r)
        + r * np.log(alpha)
        + betaln(a + 1, b + x_safe - 1) - betaln(a, b)
        - (r + x_safe) * np.log(alpha + np.maximum(t_x, 1e-30))
    )
    ln_A2 = np.where(x > 0, ln_A2_raw, -np.inf)

    ll = np.logaddexp(ln_A1, ln_A2).sum()
    if not np.isfinite(ll):
        return 1e18
    return -ll


def fit_bgnbd(frequency, recency, T):
    freq = np.asarray(frequency, dtype=float)
    rec = np.asarray(recency, dtype=float)
    t = np.asarray(T, dtype=float)

    starts = [
        np.log([0.5, 5.0, 0.5, 3.0]),
        np.log([1.0, 1.0, 1.0, 1.0]),
        np.log([0.2, 4.0, 0.8, 2.5]),
        np.log([0.1, 10.0, 0.5, 5.0]),
        np.log([1.0, 10.0, 1.0, 5.0]),
        np.log([0.3, 3.0, 1.0, 2.0]),
    ]

    best = None
    best_nll = np.inf
    for x0 in starts:
        try:
            res = minimize(
                _bgnbd_nll, x0, args=(freq, rec, t),
                method="Nelder-Mead",
                options={"maxiter": 10000, "xatol": 1e-8, "fatol": 1e-10},
            )
            if res.fun < best_nll:
                best_nll = res.fun
                best = res
        except Exception:
            continue

    r, alpha, a, b = np.exp(best.x)
    return {"r": float(r), "alpha": float(alpha), "a": float(a), "b": float(b)}


# ===================================================================
# Gamma-Gamma model
# ===================================================================

def _gg_nll(log_params, frequency, monetary_value):
    p, q, v = np.exp(log_params)
    if q <= 1.0:
        return 1e18

    mask = (frequency > 0) & (monetary_value > 0)
    x = frequency[mask].astype(float)
    m = monetary_value[mask]

    ll = (
        gammaln(p * x + q) - gammaln(p * x) - gammaln(q)
        + q * np.log(v)
        + p * x * np.log(x) + (p * x - 1) * np.log(m)
        - (p * x + q) * np.log(x * m + v)
    )
    total = ll.sum()
    if not np.isfinite(total):
        return 1e18
    return -total


def fit_gamma_gamma(frequency, monetary_value):
    freq = np.asarray(frequency, dtype=float)
    mv = np.asarray(monetary_value, dtype=float)

    starts = [
        np.log([5.0, 3.0, 15.0]),
        np.log([1.0, 2.0, 1.0]),
        np.log([10.0, 5.0, 20.0]),
        np.log([3.0, 2.0, 10.0]),
        np.log([8.0, 4.0, 10.0]),
    ]

    best = None
    best_nll = np.inf
    for x0 in starts:
        try:
            res = minimize(
                _gg_nll, x0, args=(freq, mv),
                method="Nelder-Mead",
                options={"maxiter": 10000, "xatol": 1e-8, "fatol": 1e-10},
            )
            if res.fun < best_nll and np.exp(res.x[1]) > 1.0:
                best_nll = res.fun
                best = res
        except Exception:
            continue

    p, q, v = np.exp(best.x)
    return {"p": float(p), "q": float(q), "v": float(v)}


# ===================================================================
# Per-customer predictions
# ===================================================================

def p_alive(r, alpha, a, b, x, t_x, T):
    if x == 0:
        return 1.0
    return 1.0 / (1.0 + (a / (b + x - 1)) * ((alpha + T) / (alpha + t_x)) ** (r + x))


def conditional_expected_purchases(t, r, alpha, a, b, x, t_x, T):
    pa = p_alive(r, alpha, a, b, x, t_x, T)
    z = t / (alpha + T + t)
    hyp = float(hyp2f1(r + x, b + x, a + b + x - 1, z))
    ratio = ((alpha + T) / (alpha + T + t)) ** (r + x)
    first = (a + b + x - 1) / (a - 1)
    return first * (1 - ratio * hyp) * pa


def predicted_monetary(p, q, v, x, m):
    if x == 0 or m <= 0:
        return 0.0
    return p * (v + x * m) / (p * x + q - 1)


# ===================================================================
# Main
# ===================================================================

def main():
    customers, config = load_and_clean_transactions(
        "/app/data/transactions.csv", "/app/data/config.json"
    )

    frequency = [d["frequency"] for d in customers]
    recency = [d["recency"] for d in customers]
    T = [d["T"] for d in customers]
    monetary = [d["monetary_value"] for d in customers]

    print("Fitting frequency model ...")
    fp = fit_bgnbd(frequency, recency, T)
    print(f"  params: {fp}")

    print("Fitting monetary model ...")
    mp = fit_gamma_gamma(frequency, monetary)
    print(f"  params: {mp}")

    horizon = config["prediction_horizon_weeks"]
    r, alpha, a, b = fp["r"], fp["alpha"], fp["a"], fp["b"]
    p, q, v = mp["p"], mp["q"], mp["v"]

    print("Computing per-customer predictions ...")
    predictions = []
    for d in customers:
        pa = p_alive(r, alpha, a, b, d["frequency"], d["recency"], d["T"])
        cep = conditional_expected_purchases(
            horizon, r, alpha, a, b, d["frequency"], d["recency"], d["T"],
        )
        pmv = predicted_monetary(p, q, v, d["frequency"], d["monetary_value"])
        clv = cep * pmv
        predictions.append({
            "customer_id": d["customer_id"],
            "p_alive": pa,
            "cond_expected_purchases": cep,
            "predicted_monetary_value": pmv,
            "clv": clv,
        })

    os.makedirs("/app/results", exist_ok=True)

    with open("/app/results/frequency_params.json", "w") as f:
        json.dump(fp, f, indent=2)

    with open("/app/results/monetary_params.json", "w") as f:
        json.dump(mp, f, indent=2)

    with open("/app/results/predictions.csv", "w") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "customer_id", "p_alive", "cond_expected_purchases",
            "predicted_monetary_value", "clv",
        ])
        writer.writeheader()
        for pred in predictions:
            writer.writerow({
                "customer_id": pred["customer_id"],
                "p_alive": f"{pred['p_alive']:.10f}",
                "cond_expected_purchases": f"{pred['cond_expected_purchases']:.10f}",
                "predicted_monetary_value": f"{pred['predicted_monetary_value']:.6f}",
                "clv": f"{pred['clv']:.6f}",
            })

    total_clv = sum(p_["clv"] for p_ in predictions)
    sorted_preds = sorted(predictions, key=lambda x: x["clv"], reverse=True)
    top_10 = [p_["customer_id"] for p_ in sorted_preds[:10]]

    summary = {
        "total_clv": round(total_clv, 2),
        "top_10_customer_ids": top_10,
        "mean_p_alive": round(
            float(np.mean([p_["p_alive"] for p_ in predictions])), 4
        ),
        "total_expected_purchases": round(
            sum(p_["cond_expected_purchases"] for p_ in predictions), 2
        ),
    }
    with open("/app/results/summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"Total CLV: {total_clv:.2f}")
    print(f"Top-10 customers: {top_10}")
    print("Done.")


if __name__ == "__main__":
    main()
