
"""Outcome-focused tests for the auto insurance pricing task."""

import json
import os

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm
from scipy.optimize import minimize_scalar
from statsmodels.stats.outliers_influence import variance_inflation_factor

RESULTS = '/app/results'
DATA = '/app/data'

# Columns that must never be used as predictors (targets + ID + leakage)
TARGET_COLS = {'policy_id', 'claim_count', 'claim_severity', 'total_loss'}
LEAKAGE_COL = 'risk_score'
COLLINEAR_PAIR = {'years_licensed', 'driving_experience'}


@pytest.fixture
def policies():
    return pd.read_csv(f'{DATA}/policies.csv')


@pytest.fixture
def profiles():
    return pd.read_csv(f'{DATA}/profiles.csv')


def _build_reference_model(df, prof, drop_extra=None):
    """Build a known-good reference model for comparison.

    Excludes risk_score (leakage) and driving_experience (collinear)
    plus any additional columns in drop_extra.
    """
    if drop_extra is None:
        drop_extra = set()
    exclude = TARGET_COLS | {LEAKAGE_COL, 'driving_experience'} | set(drop_extra)

    cat_cols = ['territory', 'coverage', 'gender', 'marital_status']
    input_cols = [
        c for c in df.columns
        if c not in exclude and c in prof.columns
    ]

    combined = pd.concat(
        [df[input_cols], prof[input_cols]], ignore_index=True
    )
    combined_enc = pd.get_dummies(
        combined, columns=cat_cols, drop_first=True, dtype=float
    )
    n = len(df)
    feat_cols = sorted([c for c in combined_enc.columns if c != 'exposure'])

    df_enc = combined_enc.iloc[:n].reset_index(drop=True)
    prof_enc = combined_enc.iloc[n:].reset_index(drop=True)

    # --- Frequency: Negative Binomial GLM ---
    X = sm.add_constant(df_enc[feat_cols].astype(float))
    y = df['claim_count'].values
    offset = np.log(df['exposure'].values)

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

    res = minimize_scalar(_nb_aic, bounds=(0.05, 30.0), method='bounded')
    nb_glm = sm.GLM(
        y, X,
        family=sm.families.NegativeBinomial(alpha=res.x),
        offset=offset,
    ).fit()

    Xp = sm.add_constant(prof_enc[feat_cols].astype(float))
    for col in X.columns:
        if col not in Xp.columns:
            Xp[col] = 0.0
    Xp = Xp[X.columns]

    p_off = np.log(prof['exposure'].values)
    ref_freq = nb_glm.predict(Xp, offset=p_off)

    # --- Severity: Gamma GLM with log link ---
    mask = df['claim_count'] > 0
    y_sev = df.loc[mask, 'claim_severity'].values
    Xs = sm.add_constant(df_enc.loc[mask, feat_cols].astype(float))
    gamma = sm.GLM(
        y_sev, Xs,
        family=sm.families.Gamma(link=sm.families.links.Log()),
    ).fit()
    ref_sev = gamma.predict(Xp)

    ref_pp = ref_freq * ref_sev

    # Portfolio metrics at unit exposure
    unit_freq = nb_glm.predict(X, offset=np.zeros(len(df)))
    all_sev = gamma.predict(X)
    all_pp = unit_freq * all_sev
    actual_loss = df['total_loss'].sum()
    predicted_total = (all_pp * df['exposure'].values).sum()

    return {
        'freq': ref_freq,
        'sev': ref_sev,
        'pp': ref_pp,
        'portfolio_mean_freq': float(unit_freq.mean()),
        'portfolio_mean_sev': float(all_sev.mean()),
        'portfolio_mean_pp': float(all_pp.mean()),
        'portfolio_loss_ratio': float(actual_loss / predicted_total),
    }


# ==================== FILE STRUCTURE ====================


class TestFileStructure:
    def test_diagnostics_exists(self):
        assert os.path.exists(f'{RESULTS}/diagnostics.json')

    def test_diagnostics_keys(self):
        with open(f'{RESULTS}/diagnostics.json') as f:
            d = json.load(f)
        assert 'excluded_variables' in d, "Missing key: excluded_variables"
        assert 'variable_concerns' in d, "Missing key: variable_concerns"
        assert isinstance(d['excluded_variables'], list)
        assert isinstance(d['variable_concerns'], dict)

    def test_predictions_exists(self):
        assert os.path.exists(f'{RESULTS}/predictions.csv')

    def test_predictions_columns(self):
        pred = pd.read_csv(f'{RESULTS}/predictions.csv')
        required = {'profile_id', 'predicted_frequency', 'predicted_severity', 'pure_premium'}
        assert required.issubset(pred.columns), (
            f"Missing columns: {required - set(pred.columns)}"
        )

    def test_predictions_row_count(self):
        pred = pd.read_csv(f'{RESULTS}/predictions.csv')
        assert len(pred) == 5, f"Expected 5 rows, got {len(pred)}"

    def test_portfolio_exists(self):
        assert os.path.exists(f'{RESULTS}/portfolio_summary.json')

    def test_portfolio_keys(self):
        with open(f'{RESULTS}/portfolio_summary.json') as f:
            d = json.load(f)
        required = {'mean_frequency', 'mean_severity', 'mean_pure_premium', 'observed_loss_ratio'}
        assert required.issubset(d.keys()), (
            f"Missing keys: {required - set(d.keys())}"
        )


# ==================== DIAGNOSTICS ====================


class TestDiagnostics:
    def test_leakage_variable_excluded(self):
        """Agent must discover that risk_score is derived from claim outcomes."""
        with open(f'{RESULTS}/diagnostics.json') as f:
            d = json.load(f)
        excluded = {v.lower().strip() for v in d['excluded_variables']}
        assert 'risk_score' in excluded, (
            f"risk_score (data leakage) not in excluded_variables: {d['excluded_variables']}"
        )

    def test_leakage_in_concerns(self):
        """risk_score should be flagged in variable_concerns."""
        with open(f'{RESULTS}/diagnostics.json') as f:
            d = json.load(f)
        concerns_lower = {k.lower().strip(): v for k, v in d['variable_concerns'].items()}
        assert 'risk_score' in concerns_lower, (
            f"risk_score not flagged in variable_concerns: {list(d['variable_concerns'].keys())}"
        )

    def test_collinearity_detected(self):
        """At least one of the collinear pair must be excluded."""
        with open(f'{RESULTS}/diagnostics.json') as f:
            d = json.load(f)
        excluded = {v.lower().strip() for v in d['excluded_variables']}
        assert len(excluded & {'years_licensed', 'driving_experience'}) >= 1, (
            f"Collinear pair not addressed. Excluded: {d['excluded_variables']}"
        )

    def test_collinearity_in_concerns(self):
        """At least one of the collinear pair should appear in concerns."""
        with open(f'{RESULTS}/diagnostics.json') as f:
            d = json.load(f)
        concerns_lower = {k.lower().strip() for k, v in d['variable_concerns'].items()}
        pair_flagged = concerns_lower & {'years_licensed', 'driving_experience'}
        assert len(pair_flagged) >= 1, (
            f"Collinearity not flagged. Concerns: {list(d['variable_concerns'].keys())}"
        )

    def test_multiple_issues_found(self):
        """Agent should find at least 2 distinct issues."""
        with open(f'{RESULTS}/diagnostics.json') as f:
            d = json.load(f)
        assert len(d['variable_concerns']) >= 2, (
            f"Expected >= 2 concerns, got {len(d['variable_concerns'])}"
        )

    def test_excluded_count_reasonable(self):
        """Should exclude at least 2 variables (risk_score + one collinear)."""
        with open(f'{RESULTS}/diagnostics.json') as f:
            d = json.load(f)
        assert len(d['excluded_variables']) >= 2, (
            f"Expected >= 2 excluded, got {len(d['excluded_variables'])}"
        )

    def test_verify_leakage_independently(self, policies):
        """Independently verify that risk_score correlates with claim_count."""
        corr = policies['risk_score'].corr(policies['claim_count'])
        assert abs(corr) > 0.3, (
            f"risk_score-claim_count correlation {corr:.3f} should exceed 0.3"
        )

    def test_verify_collinearity_independently(self, policies):
        """Independently verify that years_licensed and driving_experience are collinear."""
        num_cols = [
            'driver_age', 'vehicle_age', 'credit_score', 'annual_mileage',
            'years_licensed', 'driving_experience', 'prior_claims',
            'deductible', 'household_income',
        ]
        X = sm.add_constant(policies[num_cols].astype(float))
        vifs = {}
        for i, col in enumerate(num_cols):
            vifs[col] = variance_inflation_factor(X.values, i + 1)
        assert vifs['years_licensed'] > 5 or vifs['driving_experience'] > 5, (
            f"Expected high VIF for collinear pair. Got: years_licensed={vifs['years_licensed']:.1f}, "
            f"driving_experience={vifs['driving_experience']:.1f}"
        )


# ==================== PREDICTIONS ====================


class TestPredictions:
    def test_positive_values(self):
        pred = pd.read_csv(f'{RESULTS}/predictions.csv')
        assert (pred['predicted_frequency'] >= 0).all(), "Negative frequencies"
        assert (pred['predicted_severity'] > 0).all(), "Non-positive severities"
        assert (pred['pure_premium'] >= 0).all(), "Negative pure premiums"

    def test_frequency_range(self):
        pred = pd.read_csv(f'{RESULTS}/predictions.csv')
        exposures = {1: 1.0, 2: 1.0, 3: 1.0, 4: 0.5, 5: 1.0}
        for _, row in pred.iterrows():
            pid = int(row['profile_id'])
            exp = exposures.get(pid, 1.0)
            freq_per_unit = row['predicted_frequency'] / exp
            assert 0.005 < freq_per_unit < 2.0, (
                f"Profile {pid}: freq/exposure={freq_per_unit:.4f} out of range"
            )

    def test_severity_range(self, policies):
        pred = pd.read_csv(f'{RESULTS}/predictions.csv')
        mean_sev = policies.loc[
            policies['claim_count'] > 0, 'claim_severity'
        ].mean()
        for _, row in pred.iterrows():
            assert mean_sev * 0.1 < row['predicted_severity'] < mean_sev * 5, (
                f"Profile {int(row['profile_id'])}: severity "
                f"{row['predicted_severity']:.2f} out of range"
            )

    def test_pp_equals_freq_times_sev(self):
        pred = pd.read_csv(f'{RESULTS}/predictions.csv')
        for _, row in pred.iterrows():
            expected = row['predicted_frequency'] * row['predicted_severity']
            assert abs(row['pure_premium'] - expected) < max(1.0, expected * 0.01), (
                f"Profile {int(row['profile_id'])}: PP {row['pure_premium']:.2f} "
                f"!= freq*sev {expected:.2f}"
            )

    def test_young_driver_higher_freq(self):
        """Profile 1 (age 20, urban T1) should have higher frequency than profile 2 (age 45, T2)."""
        pred = pd.read_csv(f'{RESULTS}/predictions.csv')
        p1 = pred[pred['profile_id'] == 1].iloc[0]
        p2 = pred[pred['profile_id'] == 2].iloc[0]
        assert p1['predicted_frequency'] > p2['predicted_frequency'], (
            f"Young urban driver freq ({p1['predicted_frequency']:.4f}) should exceed "
            f"middle-aged suburban ({p2['predicted_frequency']:.4f})"
        )

    def test_half_exposure_profile(self):
        """Profile 4 (exposure=0.5) should have roughly half the frequency of
        a comparable full-exposure profile, indicating correct offset handling."""
        pred = pd.read_csv(f'{RESULTS}/predictions.csv')
        p4 = pred[pred['profile_id'] == 4].iloc[0]
        # At exposure 0.5, freq should be meaningfully below 1.0 for most profiles
        assert p4['predicted_frequency'] < 1.0, (
            f"Profile 4 (exposure=0.5) freq {p4['predicted_frequency']:.4f} "
            "seems too high for half exposure"
        )

    def test_independent_prediction_accuracy(self, policies, profiles):
        """Fit reference models independently and verify predictions match."""
        ref = _build_reference_model(policies, profiles)
        pred = pd.read_csv(f'{RESULTS}/predictions.csv')

        for i in range(5):
            pid = i + 1
            row = pred[pred['profile_id'] == pid].iloc[0]
            if ref['pp'][i] > 0:
                rel = abs(row['pure_premium'] - ref['pp'][i]) / ref['pp'][i]
                assert rel < 0.40, (
                    f"Profile {pid}: PP {row['pure_premium']:.2f} vs "
                    f"reference {ref['pp'][i]:.2f} (diff {rel:.1%})"
                )

    def test_frequency_accuracy(self, policies, profiles):
        """Check individual frequency predictions against reference."""
        ref = _build_reference_model(policies, profiles)
        pred = pd.read_csv(f'{RESULTS}/predictions.csv')

        for i in range(5):
            pid = i + 1
            row = pred[pred['profile_id'] == pid].iloc[0]
            if ref['freq'][i] > 0:
                rel = abs(row['predicted_frequency'] - ref['freq'][i]) / ref['freq'][i]
                assert rel < 0.50, (
                    f"Profile {pid}: freq {row['predicted_frequency']:.4f} vs "
                    f"reference {ref['freq'][i]:.4f} (diff {rel:.1%})"
                )

    def test_severity_accuracy(self, policies, profiles):
        """Check individual severity predictions against reference."""
        ref = _build_reference_model(policies, profiles)
        pred = pd.read_csv(f'{RESULTS}/predictions.csv')

        for i in range(5):
            pid = i + 1
            row = pred[pred['profile_id'] == pid].iloc[0]
            if ref['sev'][i] > 0:
                rel = abs(row['predicted_severity'] - ref['sev'][i]) / ref['sev'][i]
                assert rel < 0.50, (
                    f"Profile {pid}: severity {row['predicted_severity']:.2f} vs "
                    f"reference {ref['sev'][i]:.2f} (diff {rel:.1%})"
                )


# ==================== PORTFOLIO SUMMARY ====================


class TestPortfolio:
    def test_frequency_reasonable(self, policies):
        with open(f'{RESULTS}/portfolio_summary.json') as f:
            d = json.load(f)
        actual = policies['claim_count'].mean() / policies['exposure'].mean()
        assert abs(d['mean_frequency'] - actual) / actual < 0.5, (
            f"mean_frequency {d['mean_frequency']:.4f} too far from "
            f"empirical rate {actual:.4f}"
        )

    def test_severity_reasonable(self, policies):
        with open(f'{RESULTS}/portfolio_summary.json') as f:
            d = json.load(f)
        actual = policies.loc[
            policies['claim_count'] > 0, 'claim_severity'
        ].mean()
        assert abs(d['mean_severity'] - actual) / actual < 0.5, (
            f"mean_severity {d['mean_severity']:.2f} too far from "
            f"empirical mean {actual:.2f}"
        )

    def test_loss_ratio_range(self):
        with open(f'{RESULTS}/portfolio_summary.json') as f:
            d = json.load(f)
        assert 0.3 < d['observed_loss_ratio'] < 3.0, (
            f"Loss ratio {d['observed_loss_ratio']:.4f} out of plausible range"
        )

    def test_pure_premium_positive(self):
        with open(f'{RESULTS}/portfolio_summary.json') as f:
            d = json.load(f)
        assert d['mean_pure_premium'] > 0

    def test_mean_frequency_positive(self):
        with open(f'{RESULTS}/portfolio_summary.json') as f:
            d = json.load(f)
        assert d['mean_frequency'] > 0

    def test_mean_severity_positive(self):
        with open(f'{RESULTS}/portfolio_summary.json') as f:
            d = json.load(f)
        assert d['mean_severity'] > 0

    def test_portfolio_vs_reference(self, policies, profiles):
        """Cross-check portfolio metrics against independently computed values."""
        ref = _build_reference_model(policies, profiles)
        with open(f'{RESULTS}/portfolio_summary.json') as f:
            d = json.load(f)

        # Mean frequency should be in the same ballpark
        if ref['portfolio_mean_freq'] > 0:
            rel = abs(d['mean_frequency'] - ref['portfolio_mean_freq']) / ref['portfolio_mean_freq']
            assert rel < 0.50, (
                f"mean_frequency {d['mean_frequency']:.4f} vs ref "
                f"{ref['portfolio_mean_freq']:.4f} (diff {rel:.1%})"
            )

        # Loss ratio should be similar direction
        if ref['portfolio_loss_ratio'] > 0:
            rel = abs(d['observed_loss_ratio'] - ref['portfolio_loss_ratio']) / ref['portfolio_loss_ratio']
            assert rel < 0.60, (
                f"loss_ratio {d['observed_loss_ratio']:.4f} vs ref "
                f"{ref['portfolio_loss_ratio']:.4f} (diff {rel:.1%})"
            )
