#!/usr/bin/env python3
"""Swing option pricing with energy model analytics and convergence analysis."""

import json
import math
import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq
import QuantLib as ql


def price_bs_swing():
    """Price put swing options under BSM and validate no-arbitrage bounds."""
    settlement = ql.Date.todaysDate()
    ql.Settings.instance().evaluationDate = settlement
    dc = ql.ActualActual(ql.ActualActual.ISDA)

    spot_handle = ql.QuoteHandle(ql.SimpleQuote(30.0))
    r_ts = ql.YieldTermStructureHandle(ql.FlatForward(settlement, 0.14, dc))
    q_ts = ql.YieldTermStructureHandle(ql.FlatForward(settlement, 0.02, dc))
    vol_ts = ql.BlackVolTermStructureHandle(
        ql.BlackConstantVol(settlement, ql.NullCalendar(), 0.4, dc))

    process = ql.BlackScholesMertonProcess(spot_handle, q_ts, r_ts, vol_ts)

    exercise_dates = [settlement + ql.Period(i, ql.Months) for i in range(1, 13)]
    swing_exercise = ql.SwingExercise(exercise_dates)

    swing_engine = ql.FdSimpleBSSwingEngine(process, 50, 200)
    bermudan_engine = ql.FdBlackScholesVanillaEngine(process, 50, 200)

    put_payoff = ql.PlainVanillaPayoff(ql.Option.Put, 30.0)
    bermudan_option = ql.VanillaOption(put_payoff, swing_exercise)
    bermudan_option.setPricingEngine(bermudan_engine)
    bermudan_price = bermudan_option.NPV()

    european_prices = []
    for ed in exercise_dates:
        opt = ql.VanillaOption(put_payoff, ql.EuropeanExercise(ed))
        opt.setPricingEngine(ql.AnalyticEuropeanEngine(process))
        european_prices.append(opt.NPV())

    forward_payoff = ql.VanillaForwardPayoff(ql.Option.Put, 30.0)
    results = []
    for i in range(12):
        n = i + 1
        swing_opt = ql.VanillaSwingOption(forward_payoff, swing_exercise, 0, n)
        swing_opt.setPricingEngine(swing_engine)
        swing_price = swing_opt.NPV()

        upper_bound = n * bermudan_price
        lower_bound = sum(european_prices[:n])

        results.append({
            "n": n,
            "swing_price": float(swing_price),
            "bermudan_price": float(bermudan_price),
            "european_prices": [float(p) for p in european_prices],
            "upper_bound": float(upper_bound),
            "lower_bound": float(lower_bound),
            "upper_ok": bool(swing_price <= upper_bound + 0.01),
            "lower_ok": bool(swing_price >= lower_bound - 0.04),
        })

    return results, process, forward_payoff, swing_exercise


def compute_kluge_analytics():
    """Energy spot model distributional analytics and MC cross-validation."""
    t = 182.0 / 365.0
    alpha, sig = 4.0, 1.0
    beta, eta, lam = 5.0, 5.0, 4.0
    f0, strike = 30.0, 30.0

    # Variance of log-spot centered at forward
    var = ((2 - 2 * np.exp(-2 * beta * t)) * lam / (beta * eta ** 2) +
           (1 - np.exp(-2 * alpha * t)) * sig ** 2 / alpha) / 2.0
    std_dev = np.sqrt(var)

    # Skewness (third standardized cumulant)
    g1 = ((2 - 2 * np.exp(-3 * beta * t)) * lam /
          (beta * eta ** 2)) / std_dev ** 3

    # Excess kurtosis (fourth standardized cumulant minus 3)
    e_2at = np.exp(2 * alpha * t)
    e_2bt = np.exp(2 * beta * t)
    inner = (2 * alpha * e_2at * (-1 + e_2bt) * lam +
             beta * e_2bt * (-1 + e_2at) * eta ** 2 * sig ** 2)
    term1 = inner ** 2
    term2 = (16 * alpha ** 2 * beta *
             np.exp((5 * alpha + 3 * beta) * t) * lam *
             np.cosh(2 * beta * t))
    num = 3 * (np.exp((alpha + beta) * t) * term1 + term2)
    denom = (4 * alpha ** 2 * beta ** 2 *
             np.exp(5 * (alpha + beta) * t) * eta ** 4)
    g2 = num / denom / std_dev ** 4 - 3.0

    # Option pricing via moment-matching corrections
    d = (np.log(f0 / strike) + 0.5 * std_dev ** 2) / std_dev
    n_d = norm.pdf(d)
    bs_npv = f0 * norm.cdf(d) - strike * norm.cdf(d - std_dev)

    q3 = (1.0 / math.factorial(3)) * f0 * std_dev * (2 * std_dev - d) * n_d
    q4 = (1.0 / math.factorial(4)) * f0 * std_dev * (d**2 - 3*d*std_dev - 1) * n_d
    q5 = (10.0 / math.factorial(6)) * f0 * std_dev * (
        d**4 - 5*d**3*std_dev - 6*d**2 + 15*d*std_dev + 3) * n_d

    ccs3 = bs_npv + g1 * q3
    ccs4 = ccs3 + g2 * q4
    rubinstein = ccs4 + g1 ** 2 * q5

    # Implied volatility inversion
    def implied_vol(price):
        def obj(s):
            dd = (np.log(f0 / strike) + 0.5 * s**2) / s
            return f0 * norm.cdf(dd) - strike * norm.cdf(dd - s) - price
        try:
            return float(brentq(obj, 0.001, 20.0))
        except Exception:
            return float('nan')

    implied_vols = {
        "bs": implied_vol(bs_npv),
        "ccs3": implied_vol(ccs3),
        "ccs4": implied_vol(ccs4),
        "rubinstein": implied_vol(rubinstein),
    }

    # Monte Carlo cross-validation
    np.random.seed(421)
    n_paths = 200000
    n_steps = 100
    dt = t / n_steps

    # Forward shape correction
    ps = (np.log(f0)
          - sig**2 / (4 * alpha) * (1 - np.exp(-2 * alpha * t))
          + lam / beta * np.log((eta - np.exp(-beta * t)) / (eta - 1.0)))

    X = np.zeros(n_paths)
    Y = np.zeros(n_paths)
    exp_a_dt = np.exp(-alpha * dt)
    std_X = sig * np.sqrt((1 - np.exp(-2 * alpha * dt)) / (2 * alpha))
    exp_b_dt = np.exp(-beta * dt)
    jump_prob = 1.0 - np.exp(-lam * dt)

    for _ in range(n_steps):
        X = X * exp_a_dt + std_X * np.random.normal(0, 1, n_paths)
        Y = Y * exp_b_dt
        U = np.random.uniform(0, 1, n_paths)
        mask = U < jump_prob
        nj = int(np.sum(mask))
        if nj > 0:
            Y[mask] += -np.log(np.random.uniform(0, 1, nj)) / eta

    S_T = np.exp(X + Y + ps)
    payoffs = np.maximum(0, S_T - strike)
    mc_price = float(np.mean(payoffs))
    mc_error = float(np.std(payoffs) / np.sqrt(n_paths))

    return {
        "std_dev": float(std_dev),
        "skewness": float(g1),
        "excess_kurtosis": float(g2),
        "bs_price": float(bs_npv),
        "ccs3_price": float(ccs3),
        "ccs4_price": float(ccs4),
        "rubinstein_price": float(rubinstein),
        "mc_price": mc_price,
        "mc_error": mc_error,
        "implied_vols": implied_vols,
    }


def compute_convergence(process, forward_payoff, swing_exercise):
    """Grid convergence analysis via Richardson extrapolation."""
    engines = [
        ql.FdSimpleBSSwingEngine(process, 25, 100),   # coarse
        ql.FdSimpleBSSwingEngine(process, 50, 200),   # medium
        ql.FdSimpleBSSwingEngine(process, 100, 400),   # fine
    ]

    result = {}
    for n in [1, 6, 12]:
        prices = []
        for eng in engines:
            opt = ql.VanillaSwingOption(forward_payoff, swing_exercise, 1, n)
            opt.setPricingEngine(eng)
            prices.append(float(opt.NPV()))

        # Richardson extrapolation: f_exact ~ (k^p * f_fine - f_coarse) / (k^p - 1)
        # Douglas scheme convergence
        k = 2
        p = 1
        richardson = (k**p * prices[2] - prices[1]) / (k**p - 1)

        diff_cm = prices[0] - prices[1]
        diff_mf = prices[1] - prices[2]
        ratio = diff_cm / diff_mf if abs(diff_mf) > 1e-15 else float('inf')

        result[f"n{n}"] = {
            "coarse": prices[0],
            "medium": prices[1],
            "fine": prices[2],
            "richardson": float(richardson),
            "convergence_ratio": float(ratio),
        }

    return result


if __name__ == "__main__":
    bs_swing, process, fwd_payoff, sw_exercise = price_bs_swing()
    kluge = compute_kluge_analytics()
    convergence = compute_convergence(process, fwd_payoff, sw_exercise)

    with open("/app/results.json", "w") as f:
        json.dump({
            "bs_swing": bs_swing,
            "kluge": kluge,
            "convergence": convergence,
        }, f, indent=2)
    print("Results written to /app/results.json")
