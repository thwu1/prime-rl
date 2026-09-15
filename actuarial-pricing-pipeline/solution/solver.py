#!/usr/bin/env python3

"""Actuarial frequency-severity pricing pipeline solver."""

import json
import os
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.optimize import minimize_scalar
from statsmodels.stats.outliers_influence import variance_inflation_factor

warnings.filterwarnings('ignore')


def explore_data(df):
    """Explore the dataset to identify data quality and statistical issues."""
    concerns = {}
    to_exclude = []

    # 1. Check for data leakage: correlate each numeric column with targets.
    #    Use a high threshold (0.5) since legitimate predictors can have
    #    moderate correlation with the target -- that's why they're predictors.
    #    Leakage variables are derived from outcomes and show suspiciously
    #    strong correlation.
    target_cols = ['claim_count', 'claim_severity', 'total_loss']
    num_cols = df.select_dtypes(include=[np.number]).columns
    candidate_predictors = [
        c for c in num_cols
        if c not in target_cols and c not in ['policy_id', 'exposure']
    ]

    for col in candidate_predictors:
        corr_count = abs(df[col].corr(df['claim_count']))
        corr_loss = abs(df[col].corr(df['total_loss']))
        if corr_count > 0.5 or corr_loss > 0.5:
            concerns[col] = (
                f"Suspected data leakage: correlation with claim_count={corr_count:.3f}, "
                f"total_loss={corr_loss:.3f}. Likely derived from outcome variables."
            )
            to_exclude.append(col)

    # 2. Check for multicollinearity via VIF
    modeling_num = [
        c for c in candidate_predictors
        if c not in to_exclude
    ]
    X = sm.add_constant(df[modeling_num].astype(float))
    vifs = {}
    for i, col in enumerate(modeling_num):
        vifs[col] = float(variance_inflation_factor(X.values, i + 1))

    high_vif = {k: v for k, v in vifs.items() if v > 5}
    if high_vif:
        # Drop the one with highest VIF
        worst = max(high_vif, key=high_vif.get)
        concerns[worst] = (
            f"Multicollinearity: VIF={high_vif[worst]:.1f}. "
            f"High VIF variables: {high_vif}"
        )
        to_exclude.append(worst)

        # Also flag the paired variable
        for col, v in high_vif.items():
            if col != worst and col not in concerns:
                concerns[col] = (
                    f"Multicollinearity: VIF={v:.1f}. Correlated with {worst}."
                )

    # 3. Check for censored/capped values
    if (df['household_income'] == 250001).sum() > 50:
        concerns['household_income'] = (
            f"Right-censored at 250001 ({(df['household_income'] == 250001).sum()} records). "
            f"May distort linear relationships."
        )

    return concerns, to_exclude


def encode_data(df, prof, exclude_cols):
    """Encode categorical variables consistently, excluding specified columns."""
    cat_cols = ['territory', 'coverage', 'gender', 'marital_status']
    skip = {'policy_id', 'claim_count', 'claim_severity', 'total_loss'} | set(exclude_cols)
    input_cols = [
        c for c in df.columns
        if c not in skip and c in prof.columns
    ]

    combined = pd.concat([df[input_cols], prof[input_cols]], ignore_index=True)
    combined_enc = pd.get_dummies(combined, columns=cat_cols, drop_first=True, dtype=float)

    n = len(df)
    df_enc = combined_enc.iloc[:n].reset_index(drop=True)
    prof_enc = combined_enc.iloc[n:].reset_index(drop=True)
    feat_cols = sorted([c for c in combined_enc.columns if c != 'exposure'])

    return df_enc, prof_enc, feat_cols


def fit_frequency_model(df, df_enc, feat_cols):
    """Fit and select the best count model for claim frequency."""
    X = sm.add_constant(df_enc[feat_cols].astype(float))
    y = df['claim_count'].values
    offset = np.log(df['exposure'].values)

    # Test Poisson first to check for overdispersion
    poi = sm.GLM(y, X, family=sm.families.Poisson(), offset=offset).fit()
    disp_ratio = poi.pearson_chi2 / poi.df_resid

    # Find optimal NB alpha
    def _nb_aic(alpha):
        try:
            m = sm.GLM(
                y, X,
                family=sm.families.NegativeBinomial(alpha=alpha),
                offset=offset,
            ).fit()
            return m.aic
        except Exception:
            return np.inf

    result = minimize_scalar(_nb_aic, bounds=(0.05, 30.0), method='bounded')
    nb_glm = sm.GLM(
        y, X,
        family=sm.families.NegativeBinomial(alpha=result.x),
        offset=offset,
    ).fit()

    return nb_glm, result.x


def fit_severity_model(df, df_enc, feat_cols):
    """Fit a Gamma GLM on claim severity for policies with claims."""
    mask = df['claim_count'] > 0
    y = df.loc[mask, 'claim_severity'].values
    X = sm.add_constant(df_enc.loc[mask, feat_cols].astype(float))

    gamma = sm.GLM(
        y, X, family=sm.families.Gamma(link=sm.families.links.Log())
    ).fit()
    return gamma


def main():
    os.makedirs('/app/results', exist_ok=True)

    df = pd.read_csv('/app/data/policies.csv')
    prof = pd.read_csv('/app/data/profiles.csv')

    # Step 1: Explore data and identify issues
    concerns, exclude = explore_data(df)
    print(f"Data concerns found: {list(concerns.keys())}")
    print(f"Variables to exclude: {exclude}")

    diagnostics = {
        'excluded_variables': exclude,
        'variable_concerns': concerns,
    }
    with open('/app/results/diagnostics.json', 'w') as f:
        json.dump(diagnostics, f, indent=2)

    # Step 2: Encode data excluding problematic variables
    df_enc, prof_enc, feat_cols = encode_data(df, prof, exclude)

    # Step 3: Fit frequency model
    nb_model, nb_alpha = fit_frequency_model(df, df_enc, feat_cols)
    print(f"NB alpha: {nb_alpha:.4f}")

    # Step 4: Fit severity model
    gamma_model = fit_severity_model(df, df_enc, feat_cols)

    # Step 5: Predict for profiles
    X_train = sm.add_constant(df_enc[feat_cols].astype(float))
    Xp = sm.add_constant(prof_enc[feat_cols].astype(float))
    for col in X_train.columns:
        if col not in Xp.columns:
            Xp[col] = 0.0
    Xp = Xp[X_train.columns]

    p_offset = np.log(prof['exposure'].values)
    freq = nb_model.predict(Xp, offset=p_offset)
    sev = gamma_model.predict(Xp)
    pp = freq * sev

    pred_df = pd.DataFrame({
        'profile_id': prof['profile_id'].values,
        'predicted_frequency': np.round(freq, 6),
        'predicted_severity': np.round(sev, 2),
        'pure_premium': np.round(pp, 2),
    })
    pred_df.to_csv('/app/results/predictions.csv', index=False)
    print(f"Predictions:\n{pred_df.to_string()}")

    # Step 6: Portfolio summary
    unit_freq = nb_model.predict(X_train, offset=np.zeros(len(df)))
    all_sev = gamma_model.predict(X_train)
    all_pp = unit_freq * all_sev

    actual_loss = df['total_loss'].sum()
    predicted_total = (all_pp * df['exposure'].values).sum()
    lr = actual_loss / predicted_total if predicted_total > 0 else 0.0

    portfolio = {
        'mean_frequency': round(float(unit_freq.mean()), 6),
        'mean_severity': round(float(all_sev.mean()), 2),
        'mean_pure_premium': round(float(all_pp.mean()), 2),
        'observed_loss_ratio': round(float(lr), 4),
    }
    with open('/app/results/portfolio_summary.json', 'w') as f:
        json.dump(portfolio, f, indent=2)
    print(f"Portfolio loss ratio: {portfolio['observed_loss_ratio']}")

    print("\nAll results saved to /app/results/")


if __name__ == '__main__':
    main()
