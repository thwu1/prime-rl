
"""
Verification tests for probabilistic CLV model.

Tests independently compute RFM from raw transactions, recompute
log-likelihoods and predictions from the fitted parameters, and verify
them against the agent's output.
"""

import json
import csv
import os
from datetime import datetime
import numpy as np
from scipy.special import gammaln, betaln, hyp2f1
import pytest


# ---------------------------------------------------------------------------
# RFM computation from raw transactions (independent of agent's code)
# ---------------------------------------------------------------------------

def compute_rfm():
    """Load raw transactions, clean, and compute RFM summary."""
    with open("/app/data/config.json") as f:
        config = json.load(f)
    obs_end = datetime.strptime(config["observation_end"], "%Y-%m-%d")

    # Load and clean transactions
    seen_ids = set()
    by_customer = {}
    with open("/app/data/transactions.csv") as f:
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

    rfm = {
        "customer_id": [], "frequency": [], "recency": [],
        "T": [], "monetary_value": [],
    }
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
        rfm["customer_id"].append(cid)
        rfm["frequency"].append(freq)
        rfm["recency"].append(rec)
        rfm["T"].append(t_obs)
        rfm["monetary_value"].append(mon)

    return {k: np.array(v) for k, v in rfm.items()}


def load_predictions():
    preds = {}
    with open("/app/results/predictions.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cid = int(float(row["customer_id"]))
            preds[cid] = {
                "p_alive": float(row["p_alive"]),
                "cond_expected_purchases": float(row["cond_expected_purchases"]),
                "predicted_monetary_value": float(row["predicted_monetary_value"]),
                "clv": float(row["clv"]),
            }
    return preds


# ---------------------------------------------------------------------------
# Independent model formula implementations
# ---------------------------------------------------------------------------

def bgnbd_log_likelihood(r, alpha, a, b, frequency, recency, T):
    x = frequency.astype(float)
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

    ll = np.logaddexp(ln_A1, ln_A2)
    return ll.sum()


def gamma_gamma_log_likelihood(p, q, v, frequency, monetary_value):
    mask = (frequency > 0) & (monetary_value > 0)
    x = frequency[mask].astype(float)
    m = monetary_value[mask]

    ll = (
        gammaln(p * x + q) - gammaln(p * x) - gammaln(q)
        + q * np.log(v)
        + p * x * np.log(x) + (p * x - 1) * np.log(m)
        - (p * x + q) * np.log(x * m + v)
    )
    return ll.sum()


def compute_p_alive(r, alpha, a, b, x, t_x, T):
    if x == 0:
        return 1.0
    return 1.0 / (1.0 + (a / (b + x - 1)) * ((alpha + T) / (alpha + t_x)) ** (r + x))


def compute_cond_expected_purchases(t, r, alpha, a, b, x, t_x, T):
    pa = compute_p_alive(r, alpha, a, b, x, t_x, T)
    z = t / (alpha + T + t)
    hyp = float(hyp2f1(r + x, b + x, a + b + x - 1, z))
    ratio = ((alpha + T) / (alpha + T + t)) ** (r + x)
    first = (a + b + x - 1) / (a - 1)
    return first * (1 - ratio * hyp) * pa


def compute_predicted_monetary(p, q, v, x, m):
    if x == 0 or m <= 0:
        return 0.0
    return p * (v + x * m) / (p * x + q - 1)


# ===================================================================
# Tests
# ===================================================================


class TestOutputFiles:
    """Verify that all required output files exist with correct structure."""

    def test_frequency_params_exist(self):
        assert os.path.exists("/app/results/frequency_params.json")

    def test_monetary_params_exist(self):
        assert os.path.exists("/app/results/monetary_params.json")

    def test_predictions_exist(self):
        assert os.path.exists("/app/results/predictions.csv")

    def test_summary_exist(self):
        assert os.path.exists("/app/results/summary.json")

    def test_frequency_params_format(self):
        with open("/app/results/frequency_params.json") as f:
            params = json.load(f)
        for key in ("r", "alpha", "a", "b"):
            assert key in params, f"Missing key: {key}"
            assert isinstance(params[key], (int, float)), f"{key} must be numeric"
            assert params[key] > 0, f"{key} must be positive"

    def test_monetary_params_format(self):
        with open("/app/results/monetary_params.json") as f:
            params = json.load(f)
        for key in ("p", "q", "v"):
            assert key in params, f"Missing key: {key}"
            assert isinstance(params[key], (int, float)), f"{key} must be numeric"
            assert params[key] > 0, f"{key} must be positive"

    def test_monetary_q_greater_than_one(self):
        with open("/app/results/monetary_params.json") as f:
            params = json.load(f)
        assert params["q"] > 1.0, "q must be > 1"

    def test_predictions_format(self):
        with open("/app/results/predictions.csv") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            for col in (
                "customer_id", "p_alive", "cond_expected_purchases",
                "predicted_monetary_value", "clv",
            ):
                assert col in headers, f"Missing column: {col}"
            rows = list(reader)
            assert len(rows) > 0, "predictions.csv is empty"

    def test_summary_format(self):
        with open("/app/results/summary.json") as f:
            summary = json.load(f)
        for key in ("total_clv", "top_10_customer_ids", "mean_p_alive",
                     "total_expected_purchases"):
            assert key in summary, f"Missing key: {key}"
        assert len(summary["top_10_customer_ids"]) == 10


# -------------------------------------------------------------------
# Frequency model optimality
# -------------------------------------------------------------------

class TestFrequencyOptimality:
    """Fitted frequency model params must approximately maximise the LL."""

    @pytest.fixture
    def ctx(self):
        data = compute_rfm()
        with open("/app/results/frequency_params.json") as f:
            params = json.load(f)
        return data, params

    def _ll(self, data, params):
        return bgnbd_log_likelihood(
            params["r"], params["alpha"], params["a"], params["b"],
            data["frequency"], data["recency"], data["T"],
        )

    def _perturbed_ll(self, data, params, key, factor):
        p = dict(params)
        p[key] = p[key] * factor
        return bgnbd_log_likelihood(
            p["r"], p["alpha"], p["a"], p["b"],
            data["frequency"], data["recency"], data["T"],
        )

    def test_ll_finite(self, ctx):
        data, params = ctx
        assert np.isfinite(self._ll(data, params))

    @pytest.mark.parametrize("key", ["r", "alpha", "a", "b"])
    def test_perturbation_up(self, ctx, key):
        data, params = ctx
        assert self._ll(data, params) >= self._perturbed_ll(data, params, key, 1.15) - 0.5

    @pytest.mark.parametrize("key", ["r", "alpha", "a", "b"])
    def test_perturbation_down(self, ctx, key):
        data, params = ctx
        assert self._ll(data, params) >= self._perturbed_ll(data, params, key, 0.85) - 0.5


# -------------------------------------------------------------------
# Monetary model optimality
# -------------------------------------------------------------------

class TestMonetaryOptimality:
    """Fitted monetary model params must approximately maximise the LL."""

    @pytest.fixture
    def ctx(self):
        data = compute_rfm()
        with open("/app/results/monetary_params.json") as f:
            params = json.load(f)
        return data, params

    def _ll(self, data, params):
        return gamma_gamma_log_likelihood(
            params["p"], params["q"], params["v"],
            data["frequency"], data["monetary_value"],
        )

    def _perturbed_ll(self, data, params, key, factor):
        p = dict(params)
        p[key] = p[key] * factor
        if key == "q" and p[key] <= 1.0:
            p[key] = 1.001
        return gamma_gamma_log_likelihood(
            p["p"], p["q"], p["v"],
            data["frequency"], data["monetary_value"],
        )

    def test_ll_finite(self, ctx):
        data, params = ctx
        assert np.isfinite(self._ll(data, params))

    @pytest.mark.parametrize("key", ["p", "q", "v"])
    def test_perturbation_up(self, ctx, key):
        data, params = ctx
        assert self._ll(data, params) >= self._perturbed_ll(data, params, key, 1.15) - 0.5

    @pytest.mark.parametrize("key", ["p", "q", "v"])
    def test_perturbation_down(self, ctx, key):
        data, params = ctx
        assert self._ll(data, params) >= self._perturbed_ll(data, params, key, 0.85) - 0.5


# -------------------------------------------------------------------
# Prediction correctness
# -------------------------------------------------------------------

class TestPredictions:
    """Check that per-customer predictions match the closed-form formulas."""

    @pytest.fixture
    def ctx(self):
        data = compute_rfm()
        with open("/app/results/frequency_params.json") as f:
            fp = json.load(f)
        with open("/app/results/monetary_params.json") as f:
            mp = json.load(f)
        with open("/app/data/config.json") as f:
            cfg = json.load(f)
        preds = load_predictions()
        return data, fp, mp, cfg, preds

    def test_p_alive_bounds(self, ctx):
        _, _, _, _, preds = ctx
        for cid, p in preds.items():
            assert 0.0 <= p["p_alive"] <= 1.0 + 1e-9, f"OOB P(alive) for {cid}"

    def test_nonneg_expected_purchases(self, ctx):
        _, _, _, _, preds = ctx
        for cid, p in preds.items():
            assert p["cond_expected_purchases"] >= -1e-6, f"Negative purchases for {cid}"

    def test_nonneg_clv(self, ctx):
        _, _, _, _, preds = ctx
        for cid, p in preds.items():
            assert p["clv"] >= -0.01, f"Negative CLV for {cid}"

    def test_p_alive_formula(self, ctx):
        data, fp, _, _, preds = ctx
        r, alpha, a, b = fp["r"], fp["alpha"], fp["a"], fp["b"]
        for i in range(min(50, len(data["customer_id"]))):
            cid = int(data["customer_id"][i])
            expected = compute_p_alive(
                r, alpha, a, b,
                int(data["frequency"][i]),
                float(data["recency"][i]),
                float(data["T"][i]),
            )
            actual = preds[cid]["p_alive"]
            assert abs(actual - expected) < 0.01, (
                f"P(alive) mismatch cust {cid}: {actual:.6f} vs {expected:.6f}"
            )

    def test_cond_expected_purchases_formula(self, ctx):
        data, fp, _, cfg, preds = ctx
        r, alpha, a, b = fp["r"], fp["alpha"], fp["a"], fp["b"]
        t = cfg["prediction_horizon_weeks"]
        for i in range(min(30, len(data["customer_id"]))):
            cid = int(data["customer_id"][i])
            expected = compute_cond_expected_purchases(
                t, r, alpha, a, b,
                int(data["frequency"][i]),
                float(data["recency"][i]),
                float(data["T"][i]),
            )
            actual = preds[cid]["cond_expected_purchases"]
            tol = 0.05 + 0.05 * abs(expected)
            assert abs(actual - expected) < tol, (
                f"CondExp mismatch cust {cid}: {actual:.6f} vs {expected:.6f}"
            )

    def test_predicted_monetary_formula(self, ctx):
        data, _, mp, _, preds = ctx
        p, q, v = mp["p"], mp["q"], mp["v"]
        for i in range(min(50, len(data["customer_id"]))):
            cid = int(data["customer_id"][i])
            x = int(data["frequency"][i])
            m = float(data["monetary_value"][i])
            if x > 0 and m > 0:
                expected = compute_predicted_monetary(p, q, v, x, m)
                actual = preds[cid]["predicted_monetary_value"]
                tol = 0.5 + 0.02 * abs(expected)
                assert abs(actual - expected) < tol, (
                    f"Monetary mismatch cust {cid}: {actual:.4f} vs {expected:.4f}"
                )

    def test_zero_frequency_monetary_and_clv(self, ctx):
        data, _, _, _, preds = ctx
        for i in range(len(data["customer_id"])):
            cid = int(data["customer_id"][i])
            if int(data["frequency"][i]) == 0:
                assert preds[cid]["predicted_monetary_value"] == 0.0, (
                    f"Freq-0 customer {cid} should have monetary=0"
                )
                assert abs(preds[cid]["clv"]) < 0.01, (
                    f"Freq-0 customer {cid} should have clv=0"
                )

    def test_clv_consistency(self, ctx):
        _, _, _, _, preds = ctx
        for cid, p in preds.items():
            expected = p["predicted_monetary_value"] * p["cond_expected_purchases"]
            tol = 0.5 + 0.02 * abs(expected)
            assert abs(p["clv"] - expected) < tol, (
                f"CLV inconsistency cust {cid}: {p['clv']:.4f} vs {expected:.4f}"
            )

    def test_all_customers_present(self, ctx):
        data, _, _, _, preds = ctx
        for cid in data["customer_id"]:
            assert int(cid) in preds, f"Missing predictions for customer {int(cid)}"


# -------------------------------------------------------------------
# Summary
# -------------------------------------------------------------------

class TestSummary:

    def test_total_clv(self):
        with open("/app/results/summary.json") as f:
            summary = json.load(f)
        with open("/app/results/predictions.csv") as f:
            total = sum(float(r["clv"]) for r in csv.DictReader(f))
        assert abs(summary["total_clv"] - total) < 1.0, (
            f"Total CLV mismatch: summary={summary['total_clv']}, computed={total}"
        )

    def test_top_10(self):
        with open("/app/results/summary.json") as f:
            summary = json.load(f)
        with open("/app/results/predictions.csv") as f:
            rows = [
                (int(float(r["customer_id"])), float(r["clv"]))
                for r in csv.DictReader(f)
            ]
        rows.sort(key=lambda x: x[1], reverse=True)
        expected = [r[0] for r in rows[:10]]
        assert set(summary["top_10_customer_ids"]) == set(expected), (
            f"Top-10 mismatch: {summary['top_10_customer_ids']} vs {expected}"
        )

    def test_mean_p_alive(self):
        with open("/app/results/summary.json") as f:
            summary = json.load(f)
        with open("/app/results/predictions.csv") as f:
            vals = [float(r["p_alive"]) for r in csv.DictReader(f)]
        expected = sum(vals) / len(vals)
        assert abs(summary["mean_p_alive"] - expected) < 0.01, (
            f"mean_p_alive mismatch: summary={summary['mean_p_alive']}, "
            f"computed={expected}"
        )

    def test_total_expected_purchases(self):
        with open("/app/results/summary.json") as f:
            summary = json.load(f)
        with open("/app/results/predictions.csv") as f:
            total = sum(
                float(r["cond_expected_purchases"]) for r in csv.DictReader(f)
            )
        assert abs(summary["total_expected_purchases"] - total) < 1.0, (
            f"total_expected_purchases mismatch: "
            f"summary={summary['total_expected_purchases']}, computed={total}"
        )
