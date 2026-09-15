"""Complete ZNE inference implementations.

"""

import numpy as np
from scipy.optimize import curve_fit


class ExtrapolationFactory:
    @classmethod
    def fit_and_predict(cls, scale_factors, exp_values, predict_at):
        raise NotImplementedError

    @classmethod
    def extrapolate(cls, scale_factors, exp_values):
        return cls.fit_and_predict(
            np.asarray(scale_factors, dtype=float),
            np.asarray(exp_values, dtype=float),
            0.0,
        )


class LinearFactory(ExtrapolationFactory):
    @classmethod
    def fit_and_predict(cls, scale_factors, exp_values, predict_at):
        sf = np.asarray(scale_factors, dtype=float)
        ev = np.asarray(exp_values, dtype=float)
        coeffs = np.polyfit(sf, ev, 1)
        return float(np.polyval(coeffs, predict_at))


class RichardsonFactory(ExtrapolationFactory):
    @classmethod
    def fit_and_predict(cls, scale_factors, exp_values, predict_at):
        sf = np.asarray(scale_factors, dtype=float)
        ev = np.asarray(exp_values, dtype=float)
        n = len(sf)
        coeffs = np.polyfit(sf, ev, n - 1)
        return float(np.polyval(coeffs, predict_at))


class ExpFactory(ExtrapolationFactory):
    @classmethod
    def fit_and_predict(cls, scale_factors, exp_values, predict_at):
        sf = np.asarray(scale_factors, dtype=float)
        ev = np.asarray(exp_values, dtype=float)

        def model(x, a, b, c):
            return a + b * np.exp(c * x)

        a0 = 2.0 * ev[-1] - ev[-2]
        b0 = ev[0] - a0
        if b0 > 0 and (ev[-1] - a0) > 0 and (ev[0] - a0) > 0:
            c0 = np.log((ev[-1] - a0) / (ev[0] - a0)) / (sf[-1] - sf[0])
        else:
            c0 = -0.5

        try:
            popt, _ = curve_fit(
                model, sf, ev, p0=[a0, b0, c0], maxfev=20000
            )
        except RuntimeError:
            popt, _ = curve_fit(
                model,
                sf,
                ev,
                p0=[min(ev) * 0.5, max(ev) - min(ev) * 0.5, -0.5],
                maxfev=20000,
            )
        return float(model(predict_at, *popt))


class PolyExpFactory(ExtrapolationFactory):
    @classmethod
    def fit_and_predict(cls, scale_factors, exp_values, predict_at, order=2):
        sf = np.asarray(scale_factors, dtype=float)
        ev = np.asarray(exp_values, dtype=float)

        # Stage 1: exponential pre-fit for initial guesses
        def exp_model(x, a, b, c):
            return a + b * np.exp(c * x)

        a0 = 2.0 * ev[-1] - ev[-2]
        b0 = ev[0] - a0
        c0 = -0.5
        try:
            popt_exp, _ = curve_fit(
                exp_model, sf, ev, p0=[a0, b0, c0], maxfev=20000
            )
            a0, b0, c0 = popt_exp
        except Exception:
            pass

        # Stage 2: direct nonlinear fit with polynomial in exponent
        def model(x, a, B, c1, c2):
            return a + B * np.exp(c1 * x + c2 * x ** 2)

        try:
            popt, _ = curve_fit(
                model, sf, ev, p0=[a0, b0, c0, 0.0], maxfev=20000
            )
            return float(model(predict_at, *popt))
        except Exception:
            # Fallback: log-linearization approach
            asymptote = a0
            shifted = ev - asymptote
            sign = 1.0 if shifted[0] > 0 else -1.0
            shifted_abs = np.maximum(np.abs(shifted), 1e-30)
            log_vals = np.log(shifted_abs)
            poly_coeffs = np.polyfit(sf, log_vals, order)
            log_pred = np.polyval(poly_coeffs, predict_at)
            return float(asymptote + sign * np.exp(log_pred))
