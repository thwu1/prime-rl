"""MCMC Convergence Diagnostics Module.

Implements MCMC convergence diagnostics for analyzing pre-computed chain data.
The diagnostics should follow Vehtari et al. (2021) — "Rank-Normalization,
Folding, and Localization: An Improved R-hat for Assessing Convergence of MCMC"
(Bayesian Analysis, 16(2):667-718).

Functions operate on chain arrays with shape (n_chains, n_draws).
"""

import numpy as np
from scipy import stats


def _split_chains(chains):
    """Split each chain in half to create twice as many shorter chains.

    Parameters
    ----------
    chains : np.ndarray, shape (n_chains, n_draws)

    Returns
    -------
    np.ndarray, shape (2 * n_chains, n_draws // 2)
    """
    n_chains, n_draws = chains.shape
    half = n_draws // 2
    split = np.empty((2 * n_chains, half))
    for i in range(n_chains):
        split[2 * i] = chains[i, :half]
        split[2 * i + 1] = chains[i, half : 2 * half]
    return split


def _rank_normalize(x):
    """Replace values with their rank-normalized z-scores.

    Uses Blom's fractional rank approximation for the inverse normal CDF
    transformation: z = Phi^{-1}((rank - 3/8) / (n + 1/4))

    Parameters
    ----------
    x : np.ndarray, shape (n_chains, n_draws)

    Returns
    -------
    np.ndarray, same shape as x, with rank-normalized values
    """
    flat = x.ravel()
    n = len(flat)
    ranks = stats.rankdata(flat)
    z = stats.norm.ppf((ranks - 3 / 8) / (n + 1 / 4))
    return z.reshape(x.shape)


def compute_rhat(chains):
    """Compute the R-hat convergence diagnostic for a single parameter.

    NOTE: This should implement rank-normalized split-R-hat per Vehtari et al.
    (2021), which requires splitting chains and rank-normalizing before
    computing the R-hat statistic. The helper functions _split_chains and
    _rank_normalize are provided above for this purpose.

    Parameters
    ----------
    chains : np.ndarray, shape (n_chains, n_draws)
        MCMC samples for a single parameter across multiple chains.

    Returns
    -------
    float
        The R-hat statistic. Values close to 1.0 indicate convergence.
    """
    n_chains, n_draws = chains.shape

    # Compute within-chain variance
    chain_vars = np.var(chains, axis=1, ddof=1)
    W = np.mean(chain_vars)

    # Compute between-chain variance
    chain_means = np.mean(chains, axis=1)
    B = n_draws * np.var(chain_means, ddof=1)

    # Estimate marginal posterior variance
    var_hat = ((n_draws - 1) / n_draws) * W + B / n_draws

    if W < 1e-25:
        return 1.0

    rhat = np.sqrt(var_hat / W)
    return float(rhat)


def _autocovariance(x):
    """Compute autocovariance for a single chain using FFT.

    Uses zero-padded FFT for efficient computation of the biased
    autocovariance estimator (normalized by n).

    Parameters
    ----------
    x : np.ndarray, shape (n,)

    Returns
    -------
    np.ndarray, shape (n,), autocovariance at lags 0, 1, ..., n-1
    """
    n = len(x)
    x_centered = x - np.mean(x)

    # Zero-padded FFT for linear (non-circular) autocovariance
    fft_x = np.fft.fft(x_centered, n=2 * n)
    acov = np.fft.ifft(fft_x * np.conj(fft_x))[:n].real
    acov /= n

    return acov


def compute_ess(chains):
    """Compute effective sample size.

    Uses the autocorrelation-based ESS estimator. The autocorrelation sum
    should be truncated using the initial positive sequence estimator:
    group autocorrelations into consecutive pairs P_k = rho(2k) + rho(2k+1)
    and stop summing when the first P_k < 0.

    Parameters
    ----------
    chains : np.ndarray, shape (n_chains, n_draws)

    Returns
    -------
    float : Effective sample size
    """
    n_chains, n_draws = chains.shape

    # Compute per-chain autocovariance
    acov_per_chain = np.array([_autocovariance(chains[i]) for i in range(n_chains)])

    # Average autocovariance across chains
    mean_acov = np.mean(acov_per_chain, axis=0)

    # Within-chain variance
    W = np.mean(np.var(chains, axis=1, ddof=1))

    # Between-chain variance
    chain_means = np.mean(chains, axis=1)
    B = n_draws * np.var(chain_means, ddof=1)

    # Combined variance estimate
    var_hat = ((n_draws - 1) / n_draws) * W + B / n_draws

    if var_hat < 1e-25:
        return float(n_chains * n_draws)

    # Compute rho_hat(t)
    rho_hat = 1.0 - (W - mean_acov) / var_hat

    # Sum ALL autocorrelations without truncation
    tau_hat = -1 + 2 * np.sum(rho_hat)

    # ESS
    ess = n_chains * n_draws / tau_hat
    return float(ess)


def compute_bulk_ess(chains):
    """Compute bulk effective sample size using rank-normalized values.

    Bulk ESS measures sampling efficiency for the bulk of the distribution.
    It should be computed on rank-normalized, split chains using the
    initial positive sequence estimator for autocorrelation truncation.

    Parameters
    ----------
    chains : np.ndarray, shape (n_chains, n_draws)

    Returns
    -------
    float : Bulk ESS
    """
    raise NotImplementedError("Bulk ESS computation not yet implemented")


def compute_tail_ess(chains):
    """Compute tail effective sample size.

    Tail ESS measures sampling efficiency in the tails of the distribution.
    Computed as min(ESS(I(x <= q_0.05)), ESS(I(x <= q_0.95))) where the
    quantiles are taken from the pooled draws and ESS is computed on the
    binary indicator chains.

    Parameters
    ----------
    chains : np.ndarray, shape (n_chains, n_draws)

    Returns
    -------
    float : Tail ESS
    """
    raise NotImplementedError("Tail ESS computation not yet implemented")


def compute_mcse_mean(chains):
    """Compute Monte Carlo Standard Error for the posterior mean.

    MCSE quantifies the uncertainty in the MCMC estimate of the posterior
    mean: MCSE = posterior_sd / sqrt(bulk_ESS)

    Parameters
    ----------
    chains : np.ndarray, shape (n_chains, n_draws)

    Returns
    -------
    float : MCSE for the posterior mean
    """
    raise NotImplementedError("MCSE computation not yet implemented")


def compute_waic(log_lik):
    """Compute Widely Applicable Information Criterion (WAIC).

    WAIC = -2 * (lppd - p_waic) where:
    - lppd = sum_i log(1/S * sum_s exp(log_lik_{i,s}))  [log pointwise predictive density]
    - p_waic = sum_i Var_s(log_lik_{i,s})  [effective number of parameters]

    Must handle extreme log-likelihood values without numerical issues.

    Parameters
    ----------
    log_lik : np.ndarray, shape (n_chains, n_draws, n_obs)
        Pointwise log-likelihood values.

    Returns
    -------
    dict : {'waic': float, 'lppd': float, 'p_waic': float, 'waic_se': float}
    """
    n_chains, n_draws, n_obs = log_lik.shape

    # Pool across chains: (n_total_samples, n_obs)
    pooled = log_lik.reshape(-1, n_obs)
    S = pooled.shape[0]

    # Compute log pointwise predictive density
    lppd_i = np.log(np.mean(np.exp(pooled), axis=0))
    lppd = np.sum(lppd_i)

    # Effective number of parameters (using population variance)
    p_waic_i = np.var(pooled, axis=0)
    p_waic = np.sum(p_waic_i)

    # WAIC
    waic = -2 * (lppd - p_waic)

    # Standard error
    waic_i = -2 * (lppd_i - p_waic_i)
    waic_se = float(np.sqrt(n_obs * np.var(waic_i)))

    return {
        "waic": float(waic),
        "lppd": float(lppd),
        "p_waic": float(p_waic),
        "waic_se": waic_se,
    }


def generate_report(rhat_dict, bulk_ess_dict, tail_ess_dict, param_names):
    """Generate convergence report classifying each parameter.

    Classification criteria:
    - "converged": R-hat < 1.01 AND bulk_ESS > 400 AND tail_ESS > 400
    - "marginal": R-hat < 1.05 AND bulk_ESS > 100 AND tail_ESS > 100
    - "failed": anything else

    Parameters
    ----------
    rhat_dict : dict - parameter name -> R-hat value
    bulk_ess_dict : dict - parameter name -> bulk ESS value
    tail_ess_dict : dict - parameter name -> tail ESS value
    param_names : list of str - parameter names

    Returns
    -------
    dict with keys 'converged', 'marginal', 'failed', each a list of param names
    """
    raise NotImplementedError("Report generation not yet implemented")
