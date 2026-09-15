#!/usr/bin/env python3
"""
Count regression model comparison pipeline for doctor-visits data.
Fits truncated and hurdle count models, performs model comparison.
"""

import json
import warnings

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.discrete.truncated_model import (
    TruncatedLFNegativeBinomialP,
    TruncatedLFPoisson,
)
from statsmodels.tools.tools import add_constant


def load_data():
    return pd.read_csv("/app/data/racd10.csv")


def make_exog(df, cols=None):
    """Design matrix with intercept appended last."""
    if cols is None:
        cols = ["aget", "totchr"]
    X = df[cols].values.astype(np.float64)
    return add_constant(X, prepend=False)


def fit_truncated_model(endog, exog, truncation=0, family="poisson"):
    """Fit a truncated count model."""
    if family == "poisson":
        model = TruncatedLFPoisson(endog, exog, truncation=truncation)
    else:
        # NB1 mean-variance specification
        model = TruncatedLFNegativeBinomialP(
            endog, exog, truncation=truncation, p=1
        )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = model.fit(method="bfgs", maxiter=5000, disp=False)
    return model, result


def build_model_output(model, result, has_alpha=False):
    """Assemble result dict for a truncated model."""
    params = result.params
    bse = result.bse

    out = {
        "params": {
            "aget": float(params[0]),
            "totchr": float(params[1]),
            "const": float(params[2]),
        },
        "bse": {
            "aget": float(bse[0]),
            "totchr": float(bse[1]),
            "const": float(bse[2]),
        },
        "llf": float(result.llf),
    }

    k_exog = model.exog.shape[1]
    if has_alpha:
        # Dispersion stored internally as log(alpha)
        out["params"]["alpha"] = float(np.exp(params[k_exog]))
        # Compute AIC for NB models
        out["aic"] = float(-2.0 * result.llf + 2.0 * k_exog)
    else:
        out["aic"] = float(result.aic)

    out["n_obs"] = int(model.endog.shape[0])

    # Conditional mean at covariate means
    df_all = load_data()
    x_mean = make_exog(df_all).mean(axis=0).reshape(1, -1)
    out["conditional_mean_atmeans"] = float(
        model.predict(result.params, exog=x_mean, which="mean")[0]
    )

    return out


def main():
    df = load_data()
    endog = df["docvis"].values.astype(np.float64)

    results = {}

    # Truncation = 0 models
    exog_0 = make_exog(df)

    m0p, r0p = fit_truncated_model(endog, exog_0, truncation=0, family="poisson")
    results["trunc_poisson_0"] = build_model_output(m0p, r0p)

    m0n, r0n = fit_truncated_model(endog, exog_0, truncation=0, family="negbin")
    results["trunc_negbin_0"] = build_model_output(m0n, r0n, has_alpha=True)

    # Truncation = 1 models — validate predictors and build exog
    pred_set = {"aget", "totchr"}
    pred_names = [c for c in df.columns if c in pred_set]
    exog_1 = make_exog(df, cols=pred_names)

    m1p, r1p = fit_truncated_model(endog, exog_1, truncation=1, family="poisson")
    results["trunc_poisson_1"] = build_model_output(m1p, r1p)

    m1n, r1n = fit_truncated_model(endog, exog_1, truncation=1, family="negbin")
    results["trunc_negbin_1"] = build_model_output(m1n, r1n, has_alpha=True)

    # Likelihood ratio tests: compare Poisson vs NB at each truncation
    results["lr_test_0"] = {
        "statistic": float(2.0 * (r0p.llf - r0n.llf)),
        "df": 1,
    }
    results["lr_test_1"] = {
        "statistic": float(2.0 * (r1p.llf - r1n.llf)),
        "df": 1,
    }

    # Hurdle model (not yet implemented)
    results["hurdle_pp"] = {
        "zero_params": {"aget": 0.0, "totchr": 0.0, "const": 0.0},
        "count_params": {"aget": 0.0, "totchr": 0.0, "const": 0.0},
        "llf": 0.0,
        "predicted_mean_atmeans": 0.0,
        "predicted_probs_atmeans": [0.0, 0.0, 0.0, 0.0],
        "decomposition": {"zero_llf": 0.0, "count_llf": 0.0, "total_llf": 0.0},
    }

    # Vuong test (not yet implemented)
    results["vuong_test_0"] = {"statistic": 0.0, "pvalue": 1.0}

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Pipeline completed.")


if __name__ == "__main__":
    main()
