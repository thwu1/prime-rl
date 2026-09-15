#!/usr/bin/env python3
"""
Correct implementation: swing option pricing with energy model analytics
and grid convergence analysis via Richardson extrapolation.
Fixes all 7 defects in the buggy /app/kluge_swing.py:
1. Skewness: eta**3 (not eta**2) in denominator
2. Kurtosis: sinh (not cosh)
3. Shape correction: minus sign for jump term
4. Lower bound: last n European prices (not first n)
5. Implied vol: annualized (divide total std dev by sqrt(t))
6. Convergence: minExerciseRights=0 (not 1)
7. Richardson extrapolation: convergence order p=2 (not p=1)
"""

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
    r_ts = ql.YieldTermStructureHandle(
        ql.FlatForward(settlement, 0.14, dc))
    q_ts = ql.YieldTermStructureHandle(
        ql.FlatForward(settlement, 0.02, dc))
    vol_ts = ql.BlackVolTermStructureHandle(
        ql.BlackConstantVol(settlement, ql.NullCalendar(), 0.4, dc))

    process = ql.BlackScholesMertonProcess(spot_handle, q_ts, r_ts, vol_ts)

    exercise_dates = []
    for i in range(1, 13):
        exercise_dates.append(settlement + ql.Period(i, ql.Months))

    swing_exercise = ql.SwingExercise(exercise_dates)

    swing_engine = ql.FdSimpleBSSwingEngine(process, 50, 200)
    bermudan_engine = ql.FdBlackScholesVanillaEngine(process, 50, 200)

    put_payoff = ql.PlainVanillaPayoff(ql.Option.Put, 30.0)
    bermudan_option = ql.VanillaOption(put_payoff, swing_exercise)
    bermudan_option.setPricingEngine(bermudan_engine)
    bermudan_price = bermudan_option.NPV()

    european_prices = []
    for ed in exercise_dates:
        euro_opt = ql.VanillaOption(
            put_payoff, ql.EuropeanExercise(ed))
        euro_opt.setPricingEngine(ql.AnalyticEuropeanEngine(process))
        european_prices.append(euro_opt.NPV())

    # FIX 4: Use VanillaForwardPayoff for swing (matches C++ test)
    forward_payoff = ql.VanillaForwardPayoff(ql.Option.Put, 30.0)
    results = []
    for i in range(len(exercise_dates)):
        n = i + 1
        swing_opt = ql.VanillaSwingOption(
            forward_payoff, swing_exercise, 0, n)
        swing_opt.setPricingEngine(swing_engine)
        swing_price = swing_opt.NPV()

        upper_bound = n * bermudan_price
        # FIX 4: Sum of LAST n European prices (nearest maturity)
        lower_bound = sum(european_prices[len(exercise_dates) - n:])

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
    """Kluge model moment-matching analytics and Monte Carlo cross-validation."""
    t = 182.0 / 365.0
    alpha, sig = 4.0, 1.0
    beta, eta, lam = 5.0, 5.0, 4.0
    f0, strike = 30.0, 30.0

    # Variance
    var = ((2 - 2 * np.exp(-2 * beta * t)) * lam / (beta * eta ** 2) +
           (1 - np.exp(-2 * alpha * t)) * sig ** 2 / alpha) / 2.0
    std_dev = np.sqrt(var)

    # FIX 1: Skewness uses eta**3 (not eta**2)
    g1 = ((2 - 2 * np.exp(-3 * beta * t)) * lam /
          (beta * eta ** 3)) / std_dev ** 3

    # FIX 2: Kurtosis uses sinh (not cosh)
    e_2at = np.exp(2 * alpha * t)
    e_2bt = np.exp(2 * beta * t)
    inner = (2 * alpha * e_2at * (-1 + e_2bt) * lam +
             beta * e_2bt * (-1 + e_2at) * eta ** 2 * sig ** 2)
    term1 = inner ** 2
    term2 = (16 * alpha ** 2 * beta *
             np.exp((5 * alpha + 3 * beta) * t) * lam *
             np.sinh(2 * beta * t))
    num = 3 * (np.exp((alpha + beta) * t) * term1 + term2)
    denom = (4 * alpha ** 2 * beta ** 2 *
             np.exp(5 * (alpha + beta) * t) * eta ** 4)
    g2 = num / denom / std_dev ** 4 - 3.0

    # Black's formula
    d = (np.log(f0 / strike) + 0.5 * std_dev ** 2) / std_dev
    n_d = norm.pdf(d)
    bs_npv = f0 * norm.cdf(d) - strike * norm.cdf(d - std_dev)

    # Moment-matching corrections
    q3 = (1.0 / math.factorial(3)) * f0 * std_dev * \
         (2 * std_dev - d) * n_d
    q4 = (1.0 / math.factorial(4)) * f0 * std_dev * \
         (d ** 2 - 3 * d * std_dev - 1) * n_d
    q5 = (10.0 / math.factorial(6)) * f0 * std_dev * \
         (d ** 4 - 5 * d ** 3 * std_dev - 6 * d ** 2 +
          15 * d * std_dev + 3) * n_d

    ccs3 = bs_npv + g1 * q3
    ccs4 = ccs3 + g2 * q4
    rubinstein = ccs4 + g1 ** 2 * q5

    # FIX 5: Implied vols - solve for annualized vol, not total std dev
    def compute_implied_vol(price):
        def obj(vol_ann):
            s = vol_ann * np.sqrt(t)
            dd = (np.log(f0 / strike) + 0.5 * s ** 2) / s
            return f0 * norm.cdf(dd) - strike * norm.cdf(dd - s) - price
        try:
            return float(brentq(obj, 0.001, 20.0))
        except Exception:
            return float('nan')

    implied_vols = {
        "bs": compute_implied_vol(bs_npv),
        "ccs3": compute_implied_vol(ccs3),
        "ccs4": compute_implied_vol(ccs4),
        "rubinstein": compute_implied_vol(rubinstein),
    }

    # Monte Carlo
    np.random.seed(421)
    n_paths = 200000
    n_steps = 100
    dt = t / n_steps

    # FIX 3: Shape correction uses MINUS for jump term
    ps = (np.log(f0)
          - sig ** 2 / (4 * alpha) * (1 - np.exp(-2 * alpha * t))
          - lam / beta * np.log((eta - np.exp(-beta * t)) / (eta - 1.0)))

    X = np.zeros(n_paths)
    Y = np.zeros(n_paths)

    exp_a_dt = np.exp(-alpha * dt)
    std_X = sig * np.sqrt((1 - np.exp(-2 * alpha * dt)) / (2 * alpha))
    exp_b_dt = np.exp(-beta * dt)
    jump_prob = 1.0 - np.exp(-lam * dt)

    for _ in range(n_steps):
        Z = np.random.normal(0, 1, n_paths)
        X = X * exp_a_dt + std_X * Z

        Y = Y * exp_b_dt

        U1 = np.random.uniform(0, 1, n_paths)
        jump_mask = U1 < jump_prob
        n_jumps = int(np.sum(jump_mask))
        if n_jumps > 0:
            U2 = np.random.uniform(0, 1, n_jumps)
            Y[jump_mask] += -np.log(U2) / eta

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
            # FIX 6: minExerciseRights=0 (not 1)
            opt = ql.VanillaSwingOption(forward_payoff, swing_exercise, 0, n)
            opt.setPricingEngine(eng)
            prices.append(float(opt.NPV()))

        # FIX 7: Douglas scheme is second-order, so p=2
        k = 2
        p = 2
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
    print("Part 1: BS Swing Option Pricing...")
    bs_swing, process, fwd_payoff, sw_exercise = price_bs_swing()
    print(f"  Computed {len(bs_swing)} swing option entries")

    print("Part 2: Kluge Model Analytics + Monte Carlo...")
    kluge = compute_kluge_analytics()
    print(f"  std_dev={kluge['std_dev']:.6f}")
    print(f"  skewness={kluge['skewness']:.6f}")
    print(f"  excess_kurtosis={kluge['excess_kurtosis']:.6f}")
    print(f"  BS={kluge['bs_price']:.4f}, CCS3={kluge['ccs3_price']:.4f}, "
          f"CCS4={kluge['ccs4_price']:.4f}, Rubinstein={kluge['rubinstein_price']:.4f}")
    print(f"  MC={kluge['mc_price']:.4f} +/- {kluge['mc_error']:.4f}")

    print("Part 3: Grid Convergence Analysis...")
    convergence = compute_convergence(process, fwd_payoff, sw_exercise)
    for key in ["n1", "n6", "n12"]:
        c = convergence[key]
        print(f"  {key}: coarse={c['coarse']:.6f} medium={c['medium']:.6f} "
              f"fine={c['fine']:.6f} richardson={c['richardson']:.6f} "
              f"ratio={c['convergence_ratio']:.2f}")

    results = {
        "bs_swing": bs_swing,
        "kluge": kluge,
        "convergence": convergence,
    }
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nResults written to /app/results.json")
