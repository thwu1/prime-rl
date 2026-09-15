#!/usr/bin/env python3

"""
Solution: Robust extreme value analysis pipeline using trimmed L-moments.

Uses the lmo library for:
  - Trimmed L-statistics computation
  - L-GMM distribution fitting via lmo.inference.fit()
  - Nonparametric l_poly distribution construction
  - L-comoment analysis
  - Empirical influence function evaluation

AICc is computed from the profile negative log-likelihood at the L-GMM
parameter estimates (standard formula), NOT from lmo's GMMResult.AICc
which uses a non-standard formula based on J-test p-values.
"""

import json
import numpy as np
from scipy import stats

import lmo
from lmo.inference import fit as l_gmm_fit
from lmo.distributions import l_poly


def compute_l_stats(data):
    """Compute L-statistics at three trim levels."""
    result = {}
    for name, trim in [('trim_0_0', (0, 0)),
                        ('trim_1_1', (1, 1)),
                        ('trim_2_2', (2, 2))]:
        ls = lmo.l_stats(data, trim=trim)
        result[name] = {
            'l_loc': float(ls[0]),
            'l_scale': float(ls[1]),
            'l_skew': float(ls[2]),
            'l_kurt': float(ls[3]),
        }
    return result


def compute_aicc(data, shape, loc, scale, k):
    """Compute AICc from profile negative log-likelihood.

    AICc = 2k - 2*loglik + 2k(k+1)/(n-k-1)
    where k is the number of free parameters and n is the sample size.

    Data points yielding non-finite log-density (outside the distribution
    support) are excluded via censored likelihood.
    """
    logpdf_vals = stats.genextreme.logpdf(data, shape, loc=loc, scale=scale)
    valid = np.isfinite(logpdf_vals)
    n = int(np.sum(valid))
    if n <= k + 1:
        return float('inf')
    loglik = float(np.sum(logpdf_vals[valid]))
    aic = 2 * k - 2 * loglik
    aicc = aic + 2 * k * (k + 1) / (n - k - 1)
    return float(aicc)


def fit_distributions(data):
    """Fit GEV and Gumbel using L-GMM with over-identifying conditions."""
    trim = (1, 1)

    # Compute 5 sample L-moments (orders 1..5) with (1,1) trimming.
    # GEV has 3 free params -> 5-3 = 2 over-identifying conditions.
    # Gumbel has 2 free params -> 5-2 = 3 over-identifying conditions.
    sample_lm = lmo.l_moment(data, np.arange(1, 6), trim=trim)
    n_obs = len(data)

    # --- GEV fit (shape c, loc, scale) ---
    def gev_ppf(q, c, loc, scale):
        return stats.genextreme.ppf(q, c, loc=loc, scale=scale)

    def gev_lm_fn(r, c, loc, scale, trim):
        return stats.genextreme.l_moment(r, c, loc=loc, scale=scale, trim=trim)

    # Initial guess from data moments
    med = float(np.median(data))
    iqr = float(np.subtract(*np.percentile(data, [75, 25])))

    gev_result = l_gmm_fit(
        ppf=gev_ppf,
        args0=[0.0, med, max(iqr * 0.5, 1.0)],
        n_obs=n_obs,
        l_moments=sample_lm,
        trim=trim,
        random_state=42,
        l_moment_fn=gev_lm_fn,
    )

    # --- Gumbel fit (loc, scale; shape fixed to 0) ---
    def gumbel_ppf(q, loc, scale):
        return stats.genextreme.ppf(q, 0, loc=loc, scale=scale)

    def gumbel_lm_fn(r, loc, scale, trim):
        return stats.genextreme.l_moment(r, 0, loc=loc, scale=scale, trim=trim)

    gumbel_result = l_gmm_fit(
        ppf=gumbel_ppf,
        args0=[med, max(iqr * 0.5, 1.0)],
        n_obs=n_obs,
        l_moments=sample_lm,
        trim=trim,
        random_state=42,
        l_moment_fn=gumbel_lm_fn,
    )

    fits = {}

    # GEV: 3 free parameters
    gev_args = gev_result.args
    fits['gev'] = {
        'params': [float(gev_args[0]), float(gev_args[1]), float(gev_args[2])],
        'j_test_pvalue': float(gev_result.j_test.pvalue),
        'aicc': compute_aicc(data, gev_args[0], gev_args[1], gev_args[2], k=3),
    }

    # Gumbel: shape is fixed to 0, store as [0, loc, scale]; 2 free parameters
    gumbel_args = gumbel_result.args
    fits['gumbel'] = {
        'params': [0.0, float(gumbel_args[0]), float(gumbel_args[1])],
        'j_test_pvalue': float(gumbel_result.j_test.pvalue),
        'aicc': compute_aicc(data, 0.0, gumbel_args[0], gumbel_args[1], k=2),
    }

    return fits


def compute_return_levels(data, fits, best_model):
    """Compute 100-year and 1000-year return levels."""
    return_levels = {}

    # Best model return levels
    params = fits[best_model]['params']
    rl_100 = float(stats.genextreme.ppf(0.99, params[0],
                                         loc=params[1], scale=params[2]))
    rl_1000 = float(stats.genextreme.ppf(0.999, params[0],
                                          loc=params[1], scale=params[2]))
    return_levels['best_model'] = {'rl_100': rl_100, 'rl_1000': rl_1000}

    # l_poly nonparametric return levels
    # Use 6 trimmed L-moments for better polynomial approximation
    lmbda = lmo.l_moment(data, np.arange(1, 7), trim=(1, 1))
    lpoly_dist = l_poly(lmbda, trim=(1, 1))
    return_levels['l_poly'] = {
        'rl_100': float(lpoly_dist.ppf(0.99)),
        'rl_1000': float(lpoly_dist.ppf(0.999)),
    }

    return return_levels


def compute_l_comoments(biv_data):
    """Compute L-comoment matrices for bivariate data."""
    trim = (1, 1)

    # lmo multivariate functions expect (n_obs, n_vars) by default
    l_corr_mat = lmo.l_corr(biv_data, trim=trim)
    l_coscale_mat = lmo.l_coscale(biv_data, trim=trim)

    return {
        'l_corr': l_corr_mat.tolist(),
        'l_coscale': l_coscale_mat.tolist(),
    }


def compute_influence(data):
    """Evaluate empirical influence function of trimmed L-skewness."""
    trim = (1, 1)

    # l_ratio_influence returns a callable: IF(x) -> float
    # r=3 (L-skewness numerator), s=2 (L-scale denominator)
    if_func = lmo.l_ratio_influence(data, 3, 2, trim=trim)

    eval_points = np.linspace(float(data.min()), float(data.max()), 20)
    values = if_func(eval_points)

    return {
        'eval_points': eval_points.tolist(),
        'values': [float(v) for v in values],
    }


def main():
    # Load datasets
    data = np.loadtxt('/app/data/annual_maxima.csv')
    biv_data = np.loadtxt('/app/data/bivariate.csv', delimiter=',', skiprows=1)

    results = {}

    # 1. L-statistics at multiple trim levels
    results['l_stats'] = compute_l_stats(data)

    # 2. Distribution fits via L-GMM
    results['fits'] = fit_distributions(data)

    # 3. Model selection by AICc
    best_model = min(results['fits'],
                     key=lambda k: results['fits'][k]['aicc'])
    results['best_model'] = best_model

    # 4. Return levels
    results['return_levels'] = compute_return_levels(
        data, results['fits'], best_model
    )

    # 5. L-comoment analysis
    results['l_comoment'] = compute_l_comoments(biv_data)

    # 6. Influence function diagnostics
    results['influence'] = compute_influence(data)

    # Write output
    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print('Results written to /app/results.json')


if __name__ == '__main__':
    main()
