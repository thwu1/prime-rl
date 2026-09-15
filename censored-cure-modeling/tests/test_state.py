"""Tests for censored conversion rate modeling."""

import json
import csv
import pytest
import numpy as np
from scipy.special import gammainc, gammaincc, gammaln


def load_results():
    with open('/app/results.json') as f:
        return json.load(f)


def load_data():
    data = {}
    with open('/app/data/conversions.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            group = row['group']
            created = float(row['created_at'])
            observed = float(row['observed_at'])
            converted = row['converted_at'].strip()
            if converted:
                t = float(converted) - created
                e = 1
            else:
                t = observed - created
                e = 0
            if group not in data:
                data[group] = []
            data[group].append((t, e))
    result = {}
    for g in data:
        arr = np.array(data[g])
        mask = arr[:, 0] > 1e-6
        result[g] = (arr[mask, 0], arr[mask, 1].astype(int))
    return result


def ref_kaplan_meier(times, events, time_points):
    """Reference Kaplan-Meier implementation for verification."""
    event_times = np.sort(np.unique(times[events == 1]))
    surv = 1.0
    km = {}
    for t in event_times:
        n = np.sum(times >= t)
        d = np.sum((times == t) & (events == 1))
        if n > 0:
            surv *= (1.0 - d / n)
        km[t] = surv
    rates = []
    for tp in time_points:
        valid = [t for t in event_times if t <= tp]
        rates.append(1.0 - km[max(valid)] if valid else 0.0)
    return rates


# ---- Structure Tests ----

class TestStructure:
    def test_results_exists(self):
        r = load_results()
        assert 'groups' in r

    def test_both_groups(self):
        r = load_results()
        assert 'A' in r['groups'] and 'B' in r['groups']

    def test_km_fields(self):
        r = load_results()
        for g in ['A', 'B']:
            km = r['groups'][g]['kaplan_meier']
            assert 'time_points' in km and 'conversion_rates' in km
            assert len(km['conversion_rates']) == 6

    def test_weibull_fields(self):
        r = load_results()
        for g in ['A', 'B']:
            wb = r['groups'][g]['weibull']
            for f in ['c', 'lambda', 'p', 'aic']:
                assert f in wb, f"Missing field '{f}' in weibull for group {g}"

    def test_gengamma_fields(self):
        r = load_results()
        for g in ['A', 'B']:
            gg = r['groups'][g]['generalized_gamma']
            for f in ['c', 'lambda', 'p', 'k', 'aic']:
                assert f in gg, f"Missing field '{f}' in generalized_gamma for group {g}"

    def test_best_model_field(self):
        r = load_results()
        for g in ['A', 'B']:
            assert r['groups'][g]['best_model'] in ['weibull', 'generalized_gamma']

    def test_prediction_field(self):
        r = load_results()
        for g in ['A', 'B']:
            p = r['groups'][g]['predicted_conversion_365']
            assert isinstance(p, (int, float))


# ---- Parameter Validity Tests ----

class TestParamValidity:
    def test_weibull_ranges(self):
        r = load_results()
        for g in ['A', 'B']:
            wb = r['groups'][g]['weibull']
            assert 0 < wb['c'] < 1, f"Group {g}: c={wb['c']} out of (0,1)"
            assert wb['lambda'] > 0, f"Group {g}: lambda={wb['lambda']} not positive"
            assert wb['p'] > 0, f"Group {g}: p={wb['p']} not positive"
            assert np.isfinite(wb['aic']), f"Group {g}: aic not finite"

    def test_gengamma_ranges(self):
        r = load_results()
        for g in ['A', 'B']:
            gg = r['groups'][g]['generalized_gamma']
            assert 0 < gg['c'] < 1, f"Group {g}: c={gg['c']} out of (0,1)"
            assert gg['lambda'] > 0, f"Group {g}: lambda not positive"
            assert gg['p'] > 0, f"Group {g}: p not positive"
            assert gg['k'] > 0, f"Group {g}: k not positive"
            assert np.isfinite(gg['aic']), f"Group {g}: aic not finite"

    def test_prediction_range(self):
        r = load_results()
        for g in ['A', 'B']:
            p = r['groups'][g]['predicted_conversion_365']
            assert 0 < p < 1, f"Group {g}: prediction {p} out of (0,1)"


# ---- Kaplan-Meier Accuracy Tests ----

class TestKaplanMeier:
    def test_km_accuracy(self):
        """Agent's KM estimates must match independently computed reference."""
        r = load_results()
        data = load_data()
        tp = [7, 14, 30, 60, 90, 180]
        for g in ['A', 'B']:
            ref = ref_kaplan_meier(data[g][0], data[g][1], tp)
            agent = r['groups'][g]['kaplan_meier']['conversion_rates']
            for i, t in enumerate(tp):
                assert abs(ref[i] - agent[i]) < 0.03, \
                    f"Group {g} t={t}: KM ref={ref[i]:.4f} agent={agent[i]:.4f}"

    def test_km_monotonic(self):
        """Conversion rates must be non-decreasing over time."""
        r = load_results()
        for g in ['A', 'B']:
            rates = r['groups'][g]['kaplan_meier']['conversion_rates']
            for i in range(1, len(rates)):
                assert rates[i] >= rates[i - 1] - 1e-6, \
                    f"Group {g}: KM not monotonic at index {i}"


# ---- Model Fit Quality Tests ----

class TestModelFit:
    def test_weibull_matches_km(self):
        """Fitted Weibull predictions must be close to KM estimates at data time points."""
        r = load_results()
        for g in ['A', 'B']:
            wb = r['groups'][g]['weibull']
            km = r['groups'][g]['kaplan_meier']
            for t_val in [30, 60, 90]:
                idx = km['time_points'].index(t_val)
                km_val = km['conversion_rates'][idx]
                pred = wb['c'] * (1 - np.exp(-np.power(t_val * wb['lambda'], wb['p'])))
                assert abs(pred - km_val) < 0.05, \
                    f"Group {g} t={t_val}: Weibull pred={pred:.4f} KM={km_val:.4f}"

    def test_gengamma_matches_km(self):
        """Fitted generalized gamma predictions must be close to KM estimates."""
        r = load_results()
        for g in ['A', 'B']:
            gg = r['groups'][g]['generalized_gamma']
            km = r['groups'][g]['kaplan_meier']
            for t_val in [30, 60, 90]:
                idx = km['time_points'].index(t_val)
                km_val = km['conversion_rates'][idx]
                pred = gg['c'] * float(gammainc(
                    gg['k'], np.power(t_val * gg['lambda'], gg['p'])))
                assert abs(pred - km_val) < 0.05, \
                    f"Group {g} t={t_val}: GenGamma pred={pred:.4f} KM={km_val:.4f}"


# ---- AIC Consistency Tests ----

class TestAIC:
    def test_weibull_aic_consistent(self):
        """Recompute AIC from reported Weibull params and verify consistency."""
        r = load_results()
        data = load_data()
        for g in ['A', 'B']:
            times, events = data[g]
            wb = r['groups'][g]['weibull']
            c, lam, p = wb['c'], wb['lambda'], wb['p']

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
                s = np.clip((1 - c) + c * np.exp(-tl_p[cens]), 1e-15, None)
                ll += np.sum(np.log(s))

            expected_aic = -2 * ll + 6
            assert abs(wb['aic'] - expected_aic) < 50, \
                f"Group {g}: Weibull AIC {wb['aic']:.1f} vs recomputed {expected_aic:.1f}"

    def test_gengamma_aic_consistent(self):
        """Recompute AIC from reported gen-gamma params and verify consistency."""
        r = load_results()
        data = load_data()
        for g in ['A', 'B']:
            times, events = data[g]
            gg = r['groups'][g]['generalized_gamma']
            c, lam, p, k = gg['c'], gg['lambda'], gg['p'], gg['k']

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
                s = np.clip((1 - c) + c * gammaincc(k, tl_p[cens]), 1e-15, None)
                ll += np.sum(np.log(s))

            expected_aic = -2 * ll + 8
            assert abs(gg['aic'] - expected_aic) < 50, \
                f"Group {g}: GenGamma AIC {gg['aic']:.1f} vs recomputed {expected_aic:.1f}"

    def test_model_selection_consistency(self):
        """best_model must match the model with lower AIC."""
        r = load_results()
        for g in ['A', 'B']:
            wb_aic = r['groups'][g]['weibull']['aic']
            gg_aic = r['groups'][g]['generalized_gamma']['aic']
            expected = 'weibull' if wb_aic <= gg_aic else 'generalized_gamma'
            assert r['groups'][g]['best_model'] == expected, \
                f"Group {g}: best_model={r['groups'][g]['best_model']} " \
                f"but AIC says {expected} (wb={wb_aic:.1f}, gg={gg_aic:.1f})"

    def test_weibull_competitive(self):
        """For Weibull-generated data, Weibull AIC should not be much worse than GenGamma."""
        r = load_results()
        for g in ['A', 'B']:
            wb_aic = r['groups'][g]['weibull']['aic']
            gg_aic = r['groups'][g]['generalized_gamma']['aic']
            assert wb_aic <= gg_aic + 10, \
                f"Group {g}: Weibull AIC ({wb_aic:.1f}) should be near GenGamma ({gg_aic:.1f})"


# ---- Extrapolation Tests ----

class TestExtrapolation:
    def test_pred_near_asymptotic(self):
        """Predicted conversion at t=365 should approximate the true asymptotic rate."""
        r = load_results()
        true_c = {'A': 0.42, 'B': 0.68}
        for g in ['A', 'B']:
            pred = r['groups'][g]['predicted_conversion_365']
            assert abs(pred - true_c[g]) < 0.1, \
                f"Group {g}: pred={pred:.4f} expected ~{true_c[g]}"

    def test_pred_geq_km180(self):
        """Extrapolated rate at t=365 must be >= KM at t=180 (modulo tolerance)."""
        r = load_results()
        for g in ['A', 'B']:
            pred = r['groups'][g]['predicted_conversion_365']
            km_180 = r['groups'][g]['kaplan_meier']['conversion_rates'][-1]
            assert pred >= km_180 - 0.02, \
                f"Group {g}: pred {pred:.4f} < KM@180 {km_180:.4f}"

    def test_group_ordering(self):
        """Group B should have higher predicted conversion than Group A."""
        r = load_results()
        pred_a = r['groups']['A']['predicted_conversion_365']
        pred_b = r['groups']['B']['predicted_conversion_365']
        assert pred_b > pred_a, \
            f"Group B pred ({pred_b:.4f}) should exceed Group A ({pred_a:.4f})"
