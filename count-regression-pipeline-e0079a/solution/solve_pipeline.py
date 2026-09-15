#!/usr/bin/env python3
"""
Count regression model comparison pipeline for doctor-visits data.

Fits truncated Poisson, truncated NB2, and hurdle models,
computes LR tests, Vuong test, and structured predictions.
"""

import json
import warnings

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.discrete.truncated_model import (
    HurdleCountModel,
    TruncatedLFNegativeBinomialP,
    TruncatedLFPoisson,
)
from statsmodels.tools.sm_exceptions import ConvergenceWarning
from statsmodels.tools.tools import add_constant


def load_data():
    """Load the doctor-visits dataset."""
    df = pd.read_csv("/app/data/racd10.csv")
    return df


def make_exog(df):
    """Create the design matrix: aget, totchr, constant (appended last)."""
    X = df[["aget", "totchr"]].values.astype(np.float64)
    return add_constant(X, prepend=False)


def extract_params(result, model, has_alpha=False):
    """Extract named parameters from a truncated model result."""
    k_exog = model.exog.shape[1]
    params = result.params
    bse = result.bse

    param_dict = {
        "aget": float(params[0]),
        "totchr": float(params[1]),
        "const": float(params[2]),
    }
    bse_dict = {
        "aget": float(bse[0]),
        "totchr": float(bse[1]),
        "const": float(bse[2]),
    }

    if has_alpha:
        param_dict["alpha"] = float(params[k_exog])

    return param_dict, bse_dict


def conditional_mean_at_means(result, model):
    """
    Compute E[Y | Y > truncation] at estimation-sample covariate means.

    Uses model.predict(which='mean') which returns the truncated
    conditional mean, evaluated at the mean covariate vector from
    the estimation sample (rows where Y > truncation).
    """
    exog = model.exog
    x_mean = exog.mean(axis=0).reshape(1, -1)
    return float(model.predict(result.params, exog=x_mean, which="mean")[0])


def fit_truncated_poisson(endog, exog, truncation=0):
    """Fit a truncated Poisson model."""
    model = TruncatedLFPoisson(endog, exog, truncation=truncation)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=ConvergenceWarning)
        result = model.fit(method="bfgs", maxiter=5000, disp=False)
    return model, result


def fit_truncated_negbin(endog, exog, truncation=0):
    """Fit a truncated Negative Binomial (NB2) model."""
    model = TruncatedLFNegativeBinomialP(endog, exog, truncation=truncation, p=2)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=ConvergenceWarning)
        result = model.fit(method="bfgs", maxiter=5000, disp=False)
    return model, result


def fit_hurdle(endog, exog):
    """Fit a hurdle Poisson-Poisson model."""
    model = HurdleCountModel(endog, exog, dist="poisson", zerodist="poisson")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=ConvergenceWarning)
        result = model.fit(method="bfgs", maxiter=5000, disp=False)
    return model, result


def vuong_test(model1, result1, model2, result2):
    """
    Vuong (1989) non-nested likelihood ratio test.
    Positive statistic favors model 1, negative favors model 2.
    """
    ll1 = model1.loglikeobs(result1.params)
    ll2 = model2.loglikeobs(result2.params)

    m = ll1 - ll2
    n = len(m)
    m_bar = np.mean(m)
    s_m = np.std(m, ddof=1)

    v_stat = np.sqrt(n) * m_bar / s_m
    p_value = 2.0 * stats.norm.sf(np.abs(v_stat))

    return float(v_stat), float(p_value)


def build_truncated_result(model, result, has_alpha=False):
    """Build the JSON object for a truncated model."""
    param_dict, bse_dict = extract_params(result, model, has_alpha=has_alpha)
    cond_mean = conditional_mean_at_means(result, model)

    return {
        "params": param_dict,
        "bse": bse_dict,
        "llf": float(result.llf),
        "aic": float(result.aic),
        "n_obs": int(model.endog.shape[0]),
        "conditional_mean_atmeans": cond_mean,
    }


def main():
    df = load_data()
    endog = df["docvis"].values.astype(np.float64)
    exog = make_exog(df)

    results = {}

    # -- Truncated Poisson, truncation = 0 --
    mod_tp0, res_tp0 = fit_truncated_poisson(endog, exog, truncation=0)
    results["trunc_poisson_0"] = build_truncated_result(mod_tp0, res_tp0)

    # -- Truncated NB2, truncation = 0 --
    mod_tn0, res_tn0 = fit_truncated_negbin(endog, exog, truncation=0)
    results["trunc_negbin_0"] = build_truncated_result(
        mod_tn0, res_tn0, has_alpha=True)

    # -- Truncated Poisson, truncation = 1 --
    mod_tp1, res_tp1 = fit_truncated_poisson(endog, exog, truncation=1)
    results["trunc_poisson_1"] = build_truncated_result(mod_tp1, res_tp1)

    # -- Truncated NB2, truncation = 1 --
    mod_tn1, res_tn1 = fit_truncated_negbin(endog, exog, truncation=1)
    results["trunc_negbin_1"] = build_truncated_result(
        mod_tn1, res_tn1, has_alpha=True)

    # -- Hurdle Poisson-Poisson --
    mod_h, res_h = fit_hurdle(endog, exog)

    k_zeros = int(
        (len(res_h.params) - mod_h.k_extra1 - mod_h.k_extra2) / 2
    ) + mod_h.k_extra1
    params_zero = res_h.params[:k_zeros]
    params_count = res_h.params[k_zeros:]

    hurdle_zero_params = {
        "aget": float(params_zero[0]),
        "totchr": float(params_zero[1]),
        "const": float(params_zero[2]),
    }
    hurdle_count_params = {
        "aget": float(params_count[0]),
        "totchr": float(params_count[1]),
        "const": float(params_count[2]),
    }

    x_mean = exog.mean(axis=0).reshape(1, -1)
    pred_mean = mod_h.predict(res_h.params, exog=x_mean, which="mean")
    pred_probs = mod_h.predict(
        res_h.params, exog=x_mean, which="prob", y_values=np.arange(4)
    )

    zero_llf = float(res_h.results_zero.llf)
    count_llf = float(res_h.results_count.llf)

    results["hurdle_pp"] = {
        "zero_params": hurdle_zero_params,
        "count_params": hurdle_count_params,
        "llf": float(res_h.llf),
        "predicted_mean_atmeans": float(pred_mean[0]),
        "predicted_probs_atmeans": [float(p) for p in pred_probs[0]],
        "decomposition": {
            "zero_llf": zero_llf,
            "count_llf": count_llf,
            "total_llf": zero_llf + count_llf,
        },
    }

    # -- LR Tests --
    lr_stat_0 = 2.0 * (res_tn0.llf - res_tp0.llf)
    lr_stat_1 = 2.0 * (res_tn1.llf - res_tp1.llf)

    results["lr_test_0"] = {"statistic": float(lr_stat_0), "df": 1}
    results["lr_test_1"] = {"statistic": float(lr_stat_1), "df": 1}

    # -- Vuong Test --
    v_stat, v_pval = vuong_test(mod_tp0, res_tp0, mod_tn0, res_tn0)
    results["vuong_test_0"] = {"statistic": v_stat, "pvalue": v_pval}

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Pipeline completed. Results written to /app/results.json")


if __name__ == "__main__":
    main()
