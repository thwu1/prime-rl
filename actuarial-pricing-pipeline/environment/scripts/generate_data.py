#!/usr/bin/env python3
"""Generate synthetic auto insurance policies dataset for actuarial pricing task."""

import numpy as np
import pandas as pd
import os


def main():
    rng = np.random.default_rng(20231015)
    n = 10000

    driver_age = rng.integers(18, 78, n)
    vehicle_age = rng.integers(0, 22, n)
    territory = rng.choice(
        ['T1', 'T2', 'T3', 'T4', 'T5'], n, p=[0.25, 0.25, 0.20, 0.15, 0.15]
    )
    credit_score = np.clip(
        np.round(rng.normal(710, 75, n)), 300, 850
    ).astype(int)
    annual_mileage = np.clip(
        np.round(rng.lognormal(9.4, 0.45, n), -2), 1000, 50000
    ).astype(int)
    coverage = rng.choice(
        ['basic', 'standard', 'premium'], n, p=[0.30, 0.45, 0.25]
    )
    gender = rng.choice(['M', 'F'], n, p=[0.52, 0.48])
    marital_status = rng.choice(
        ['S', 'M', 'D', 'W'], n, p=[0.30, 0.45, 0.15, 0.10]
    )
    years_licensed = np.clip(
        driver_age - 16 - rng.geometric(0.4, n), 0, 55
    ).astype(int)
    prior_claims = rng.poisson(0.25, n)
    deductible = rng.choice(
        [250, 500, 1000, 2000], n, p=[0.15, 0.35, 0.30, 0.20]
    )
    exposure = np.round(np.clip(rng.beta(9, 2, n), 0.08, 1.0), 4)

    # Deliberately multicollinear with years_licensed
    driving_experience = np.round(
        years_licensed + rng.normal(0.5, 1.2, n), 1
    )
    driving_experience = np.clip(driving_experience, 0, 60)

    # Household income censored at 250001
    raw_income = np.round(rng.lognormal(10.85, 0.55, n)).astype(int)
    household_income = np.where(
        raw_income > 250000, 250001, np.clip(raw_income, 15000, 250000)
    )

    # === Frequency DGP: Negative Binomial ===
    terr_freq = {'T1': 0.35, 'T2': 0.15, 'T3': 0.0, 'T4': -0.10, 'T5': -0.20}
    cov_freq = {'basic': 0.10, 'standard': 0.0, 'premium': -0.15}
    mar_freq = {'S': 0.12, 'M': -0.08, 'D': 0.05, 'W': 0.0}

    te = np.array([terr_freq[t] for t in territory])
    ce = np.array([cov_freq[c] for c in coverage])
    me = np.array([mar_freq[m] for m in marital_status])
    young = (driver_age < 25).astype(float) * 0.25

    log_mu = (
        -1.5
        + young
        + 0.005 * (driver_age - 40)
        + 0.02 * vehicle_age
        - 0.002 * (credit_score - 700)
        + te + ce + me
        + 5e-6 * annual_mileage
        - 0.008 * years_licensed
        + 0.06 * prior_claims
        + np.log(exposure)
    )

    mu = np.exp(log_mu)
    r = 0.5  # NB dispersion (r parameter) -- low r = strong overdispersion
    p_nb = r / (r + mu)
    claim_count = rng.negative_binomial(r, p_nb)

    # === Severity DGP: Gamma ===
    terr_sev = {'T1': 0.20, 'T2': 0.10, 'T3': 0.0, 'T4': -0.05, 'T5': -0.10}
    cov_sev = {'basic': -0.10, 'standard': 0.0, 'premium': 0.15}

    ts = np.array([terr_sev[t] for t in territory])
    cs = np.array([cov_sev[c] for c in coverage])

    log_mu_sev = (
        7.5
        + 0.003 * vehicle_age
        + cs + ts
        - 0.0005 * (credit_score - 700)
        - np.log(deductible) * 0.05
    )

    mu_sev = np.exp(log_mu_sev)
    shape = 2.5
    severity = np.zeros(n)
    idx = claim_count > 0
    severity[idx] = rng.gamma(shape, mu_sev[idx] / shape)
    severity = np.round(severity, 2)

    total_loss = np.round(claim_count * severity, 2)

    # === Data leakage trap: risk_score is derived from claim outcomes ===
    # Appears to be a pre-computed underwriting score but is actually
    # a noisy function of the target variables (claim_count and severity).
    # Using a strong linear function of claim_count ensures Pearson > 0.5.
    risk_score = np.round(
        30.0 + 25.0 * claim_count + 0.005 * severity
        + rng.normal(0, 2, n),
        1,
    )
    risk_score = np.clip(risk_score, 5, 99)

    # Verify the leakage signal is strong enough
    df_check = pd.DataFrame({'risk_score': risk_score, 'claim_count': claim_count})
    corr = df_check['risk_score'].corr(df_check['claim_count'])
    assert abs(corr) > 0.5, (
        f"risk_score correlation with claim_count too weak: {corr:.3f}"
    )

    df = pd.DataFrame({
        'policy_id': range(1, n + 1),
        'driver_age': driver_age,
        'vehicle_age': vehicle_age,
        'territory': territory,
        'credit_score': credit_score,
        'annual_mileage': annual_mileage,
        'coverage': coverage,
        'gender': gender,
        'marital_status': marital_status,
        'years_licensed': years_licensed,
        'driving_experience': driving_experience,
        'prior_claims': prior_claims,
        'deductible': deductible,
        'household_income': household_income,
        'risk_score': risk_score,
        'exposure': exposure,
        'claim_count': claim_count,
        'claim_severity': severity,
        'total_loss': total_loss,
    })
    df.to_csv('/app/data/policies.csv', index=False)

    profiles = pd.DataFrame({
        'profile_id': [1, 2, 3, 4, 5],
        'driver_age': [20, 45, 68, 22, 50],
        'vehicle_age': [3, 5, 12, 1, 8],
        'territory': ['T1', 'T2', 'T5', 'T2', 'T1'],
        'credit_score': [650, 780, 720, 690, 800],
        'annual_mileage': [15000, 12000, 8000, 25000, 10000],
        'coverage': ['basic', 'standard', 'standard', 'standard', 'premium'],
        'gender': ['M', 'F', 'M', 'F', 'M'],
        'marital_status': ['S', 'M', 'W', 'S', 'M'],
        'years_licensed': [2, 27, 50, 4, 32],
        'driving_experience': [2.5, 27.5, 50.5, 4.5, 32.5],
        'prior_claims': [1, 0, 0, 2, 0],
        'deductible': [500, 1000, 2000, 500, 1000],
        'household_income': [45000, 120000, 65000, 35000, 200000],
        'risk_score': [55.0, 42.0, 48.0, 62.0, 38.0],
        'exposure': [1.0, 1.0, 1.0, 0.5, 1.0],
    })
    profiles.to_csv('/app/data/profiles.csv', index=False)

    # Generate partial data dictionary (intentionally incomplete)
    readme = """# Auto Insurance Portfolio Data

## policies.csv

| Column | Description |
|--------|-------------|
| policy_id | Unique policy identifier |
| driver_age | Age of primary driver |
| vehicle_age | Age of insured vehicle in years |
| territory | Rating territory (T1 through T5) |
| credit_score | Credit-based insurance score |
| annual_mileage | Estimated annual miles driven |
| coverage | Coverage tier |
| gender | Driver gender |
| marital_status | Marital status code |
| years_licensed | Years since first licensure |
| driving_experience | Self-reported years of driving experience |
| prior_claims | Count of prior insurance claims |
| deductible | Policy deductible amount ($) |
| household_income | Annual household income |
| risk_score | Proprietary risk assessment score |
| exposure | Fraction of policy year observed |
| claim_count | Number of claims in observation period |
| claim_severity | Average cost per claim (0 if no claims) |
| total_loss | Total incurred loss amount |

## profiles.csv

Same feature columns as policies.csv (excluding claim outcome fields). Each row is a distinct risk profile requiring a pure premium estimate.
"""
    with open('/app/data/README.md', 'w') as f:
        f.write(readme)

    print(f"Generated {len(df)} policies, {idx.sum()} with claims")
    print(f"Claim rate: {idx.mean():.3f}")
    print(f"Mean count: {df['claim_count'].mean():.3f}")
    if idx.sum() > 0:
        print(f"Mean severity (claims>0): {df.loc[idx, 'claim_severity'].mean():.2f}")
    print(f"risk_score corr with claim_count: {corr:.3f}")

    # Verify collinearity exists
    corr_yl_de = df['years_licensed'].corr(df['driving_experience'])
    print(f"years_licensed-driving_experience corr: {corr_yl_de:.3f}")


if __name__ == '__main__':
    os.makedirs('/app/data', exist_ok=True)
    main()
