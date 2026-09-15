#!/usr/bin/env python3
"""
Censored conversion rate modeling engine.
Fits Kaplan-Meier, Weibull cure model, and generalized gamma cure model
to right-censored conversion data via maximum likelihood estimation.
"""

import csv
import json
import numpy as np
from scipy.optimize import minimize
from scipy.special import gammainc, gammaincc, gammaln


def load_data(filepath):
    """Load conversion data, compute time-to-event and event indicator."""
    data = {}
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            group = row['group']
            created = float(row['created_at'])
            observed = float(row['observed_at'])
            converted = row['converted_at'].strip()
            if converted:
                time = float(converted) - created
                event = 1
            else:
                time = observed - created
                event = 0
            if group not in data:
                data[group] = []
            data[group].append((time, event))

    result = {}
    for g in data:
        times = np.array([x[0] for x in data[g]])
        events = np.array([x[1] for x in data[g]])
        mask = times > 1e-6
        result[g] = (times[mask], events[mask])
    return result


def kaplan_meier(times, events, time_points):
    """Compute Kaplan-Meier conversion rate estimates (1 - survival)."""
    event_times = np.sort(np.unique(times[events == 1]))
    surv = 1.0
    km = {}
    for t in event_times:
        at_risk = np.sum(times >= t)
        d = np.sum((times == t) & (events == 1))
        if at_risk > 0:
            surv *= (1.0 - d / at_risk)
        km[t] = surv

    rates = []
    for tp in time_points:
        valid = [t for t in event_times if t <= tp]
        if valid:
            rates.append(1.0 - km[max(valid)])
        else:
            rates.append(0.0)
    return rates


def weibull_nll(params, times, events):
    """Negative log-likelihood for Weibull cure model.
    F(t) = c * (1 - exp(-(t*lam)^p))
    S(t) = (1-c) + c * exp(-(t*lam)^p)
    f(t) = c * p * lam^p * t^(p-1) * exp(-(t*lam)^p)
    """
    c, lam, p = params
    if c <= 0 or c >= 1 or lam <= 0 or p <= 0:
        return 1e15

    tl_p = np.clip(np.power(times * lam, p), 0, 500)
    conv = events == 1
    cens = events == 0

    ll = 0.0
    if np.any(conv):
        ll += np.sum(
            np.log(c) + np.log(p) + p * np.log(lam)
            + (p - 1) * np.log(times[conv]) - tl_p[conv]
        )
    if np.any(cens):
        survival = np.clip((1 - c) + c * np.exp(-tl_p[cens]), 1e-15, None)
        ll += np.sum(np.log(survival))

    if not np.isfinite(ll):
        return 1e15
    return -ll


def gengamma_nll(params, times, events):
    """Negative log-likelihood for generalized gamma cure model.
    F(t) = c * gammainc(k, (t*lam)^p)
    S(t) = (1-c) + c * gammaincc(k, (t*lam)^p)
    f(t) = c * p * lam^(pk) * t^(pk-1) * exp(-(t*lam)^p) / Gamma(k)
    """
    c, lam, p, k = params
    if c <= 0 or c >= 1 or lam <= 0 or p <= 0 or k <= 0:
        return 1e15

    tl_p = np.clip(np.power(times * lam, p), 0, 500)
    conv = events == 1
    cens = events == 0

    ll = 0.0
    if np.any(conv):
        ll += np.sum(
            np.log(c) + np.log(p) + p * k * np.log(lam)
            + (p * k - 1) * np.log(times[conv]) - tl_p[conv] - gammaln(k)
        )
    if np.any(cens):
        survival = np.clip((1 - c) + c * gammaincc(k, tl_p[cens]), 1e-15, None)
        ll += np.sum(np.log(survival))

    if not np.isfinite(ll):
        return 1e15
    return -ll


def fit_weibull(times, events):
    """Fit Weibull cure model via MLE with multi-start optimization."""
    best = None
    best_nll = np.inf

    for c0 in [0.3, 0.5, 0.7]:
        for lam0 in [0.01, 0.03, 0.05]:
            for p0 in [0.5, 1.0, 2.0]:
                try:
                    res = minimize(
                        weibull_nll, x0=[c0, lam0, p0],
                        args=(times, events), method='L-BFGS-B',
                        bounds=[(0.01, 0.99), (0.001, 1.0), (0.1, 5.0)]
                    )
                    if res.fun < best_nll:
                        best_nll = res.fun
                        best = res
                except Exception:
                    continue

    c, lam, p = best.x
    aic = 2 * best_nll + 2 * 3
    return {'c': float(c), 'lambda': float(lam), 'p': float(p), 'aic': float(aic)}


def fit_gengamma(times, events):
    """Fit generalized gamma cure model via MLE with multi-start optimization."""
    best = None
    best_nll = np.inf

    for c0 in [0.3, 0.5, 0.7]:
        for lam0 in [0.01, 0.03]:
            for p0 in [1.0, 2.0]:
                for k0 in [0.5, 1.0, 2.0]:
                    try:
                        res = minimize(
                            gengamma_nll, x0=[c0, lam0, p0, k0],
                            args=(times, events), method='L-BFGS-B',
                            bounds=[(0.01, 0.99), (0.001, 1.0), (0.1, 5.0),
                                    (0.1, 10.0)]
                        )
                        if res.fun < best_nll:
                            best_nll = res.fun
                            best = res
                    except Exception:
                        continue

    c, lam, p, k = best.x
    aic = 2 * best_nll + 2 * 4
    return {'c': float(c), 'lambda': float(lam), 'p': float(p),
            'k': float(k), 'aic': float(aic)}


def main():
    with open('/app/config.json') as f:
        config = json.load(f)

    data = load_data(config['data_file'])
    time_points = config['km_time_points']
    extrap_t = config['extrapolation_time']

    results = {'groups': {}}

    for group in sorted(data.keys()):
        times, events = data[group]

        km = kaplan_meier(times, events, time_points)
        wb = fit_weibull(times, events)
        gg = fit_gengamma(times, events)

        best = 'weibull' if wb['aic'] <= gg['aic'] else 'generalized_gamma'

        if best == 'weibull':
            pred = wb['c'] * (1 - np.exp(
                -np.power(extrap_t * wb['lambda'], wb['p'])))
        else:
            pred = gg['c'] * float(gammainc(
                gg['k'], np.power(extrap_t * gg['lambda'], gg['p'])))

        results['groups'][group] = {
            'kaplan_meier': {
                'time_points': time_points,
                'conversion_rates': [round(float(x), 6) for x in km]
            },
            'weibull': {
                'c': round(wb['c'], 6),
                'lambda': round(wb['lambda'], 6),
                'p': round(wb['p'], 6),
                'aic': round(wb['aic'], 2)
            },
            'generalized_gamma': {
                'c': round(gg['c'], 6),
                'lambda': round(gg['lambda'], 6),
                'p': round(gg['p'], 6),
                'k': round(gg['k'], 6),
                'aic': round(gg['aic'], 2)
            },
            'best_model': best,
            'predicted_conversion_365': round(float(pred), 6)
        }

    with open(config['output_file'], 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Results written to {config['output_file']}")


if __name__ == '__main__':
    main()
