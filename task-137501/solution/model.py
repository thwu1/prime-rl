"""Censored conversion rate modeling with modified survival distributions.

Implements Kaplan-Meier estimation and parametric MLE fitting for conversion
models where not all users will ever convert (ceiling parameter c).
"""

import csv
import json
from collections import defaultdict

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
from scipy.special import logit as sp_logit


def kaplan_meier(times, events):
    """Kaplan-Meier estimator returning cumulative conversion (1-S(t))."""
    times = np.asarray(times, dtype=float)
    events = np.asarray(events, dtype=int)
    order = np.argsort(times, kind="stable")
    times = times[order]
    events = events[order]

    n = len(times)
    event_times = []
    conv_est = []
    survival = 1.0
    n_at_risk = n
    i = 0

    while i < n:
        t = times[i]
        d = 0
        c = 0
        while i < n and times[i] == t:
            if events[i] == 1:
                d += 1
            else:
                c += 1
            i += 1
        if d > 0:
            survival *= 1.0 - d / n_at_risk
            event_times.append(t)
            conv_est.append(1.0 - survival)
        n_at_risk -= d + c

    return np.array(event_times), np.array(conv_est)


def weibull_nll(params, times, events):
    """Negative log-likelihood for F(t) = c*(1 - exp(-(lam*t)^p))."""
    c, lam, p = params
    if c <= 0 or c >= 1 or lam <= 0 or p <= 0:
        return 1e10

    times = np.asarray(times, dtype=float)
    events = np.asarray(events, dtype=int)
    times = np.maximum(times, 1e-10)

    lt = lam * times
    lt_p = np.power(lt, p)

    converted = events == 1
    censored = events == 0
    ll = 0.0

    if np.any(converted):
        t_c = times[converted]
        lt_p_c = lt_p[converted]
        ll += np.sum(
            np.log(c) + np.log(p) + p * np.log(lam)
            + (p - 1.0) * np.log(t_c) - lt_p_c
        )

    if np.any(censored):
        surv = (1.0 - c) + c * np.exp(-lt_p[censored])
        surv = np.maximum(surv, 1e-300)
        ll += np.sum(np.log(surv))

    if not np.isfinite(ll):
        return 1e10
    return -ll


def _fit_weibull_once(x0, times, events):
    def _obj(x):
        return weibull_nll(
            (expit(x[0]), np.exp(x[1]), np.exp(x[2])), times, events
        )
    return minimize(_obj, x0, method="Nelder-Mead",
                    options={"maxiter": 15000, "xatol": 1e-9, "fatol": 1e-9})


def _fit_exp_once(x0, times, events):
    def _obj(x):
        return weibull_nll(
            (expit(x[0]), np.exp(x[1]), 1.0), times, events
        )
    return minimize(_obj, x0, method="Nelder-Mead",
                    options={"maxiter": 15000, "xatol": 1e-9, "fatol": 1e-9})


def fit_weibull(times, events):
    """MLE fit of the modified Weibull model.

    Returns dict with keys: c, lam, p, nll, aic.
    """
    times = np.asarray(times, dtype=float)
    events = np.asarray(events, dtype=int)
    c0 = float(np.clip(np.mean(events), 0.05, 0.95))

    best = None
    for l0 in (0.01, 0.05, 0.1):
        for p0 in (0.5, 1.0, 2.0):
            x0 = [sp_logit(c0), np.log(l0), np.log(p0)]
            try:
                r = _fit_weibull_once(x0, times, events)
                if best is None or r.fun < best.fun:
                    best = r
            except Exception:
                pass

    if best is None:
        raise RuntimeError("Weibull optimisation failed for all initialisations")

    c = float(expit(best.x[0]))
    lam = float(np.exp(best.x[1]))
    p = float(np.exp(best.x[2]))
    nll = float(best.fun)
    return {"c": c, "lam": lam, "p": p, "nll": nll, "aic": 6.0 + 2.0 * nll}


def fit_exponential(times, events):
    """MLE fit of the modified exponential (p=1) model.

    Returns dict with keys: c, lam, nll, aic.
    """
    times = np.asarray(times, dtype=float)
    events = np.asarray(events, dtype=int)
    c0 = float(np.clip(np.mean(events), 0.05, 0.95))

    best = None
    for l0 in (0.005, 0.01, 0.05, 0.1):
        x0 = [sp_logit(c0), np.log(l0)]
        try:
            r = _fit_exp_once(x0, times, events)
            if best is None or r.fun < best.fun:
                best = r
        except Exception:
            pass

    if best is None:
        raise RuntimeError("Exponential optimisation failed for all initialisations")

    c = float(expit(best.x[0]))
    lam = float(np.exp(best.x[1]))
    nll = float(best.fun)
    return {"c": c, "lam": lam, "nll": nll, "aic": 4.0 + 2.0 * nll}


def bootstrap_ci(times, events, model_type="weibull", n_boot=200, alpha=0.05):
    """Bootstrap confidence interval for the ceiling parameter c."""
    times = np.asarray(times, dtype=float)
    events = np.asarray(events, dtype=int)
    n = len(times)
    fit_fn = fit_weibull if model_type == "weibull" else fit_exponential

    c_samples = []
    for _ in range(n_boot):
        idx = np.random.choice(n, size=n, replace=True)
        try:
            c_samples.append(fit_fn(times[idx], events[idx])["c"])
        except Exception:
            pass

    if len(c_samples) < max(5, n_boot // 10):
        raise RuntimeError("Too few successful bootstrap replicates")

    c_arr = np.array(c_samples)
    return (
        float(np.percentile(c_arr, 100.0 * alpha / 2)),
        float(np.percentile(c_arr, 100.0 * (1.0 - alpha / 2))),
    )


def analyze_dataset(csv_path, output_path="/app/results.json"):
    """Full pipeline: fit both models per channel, select by AIC, bootstrap CI.

    Writes results to output_path.
    """
    data = defaultdict(lambda: {"times": [], "events": []})
    with open(csv_path) as fh:
        for row in csv.DictReader(fh):
            ch = row["channel"]
            data[ch]["times"].append(float(row["days_to_event"]))
            data[ch]["events"].append(int(row["converted"]))

    results = {}
    for ch in sorted(data.keys()):
        t = np.array(data[ch]["times"])
        e = np.array(data[ch]["events"])

        w = fit_weibull(t, e)
        x = fit_exponential(t, e)

        if w["aic"] < x["aic"]:
            best_name, best = "weibull", w
        else:
            best_name, best = "exponential", x

        ci = bootstrap_ci(t, e, best_name, n_boot=200)

        results[ch] = {
            "estimated_long_term_rate": best["c"],
            "ci_lower": ci[0],
            "ci_upper": ci[1],
            "model_type": best_name,
        }

    with open(output_path, "w") as fh:
        json.dump(results, fh, indent=2)

    return results
