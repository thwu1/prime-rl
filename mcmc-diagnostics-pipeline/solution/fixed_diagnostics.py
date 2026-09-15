"""MCMC Convergence Diagnostics Module — Corrected Implementation.

Implements modern MCMC convergence diagnostics following Vehtari et al. (2021).
"Rank-Normalization, Folding, and Localization: An Improved R-hat for Assessing
Convergence of MCMC" (Bayesian Analysis, 16(2):667-718).

"""

import numpy as np
from scipy import stats
from scipy.special import logsumexp


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
    """Rank-normalize using Blom's fractional rank approximation.

    z = Phi^{-1}((rank - 3/8) / (n + 1/4))

    Parameters
    ----------
    x : np.ndarray, shape (n_chains, n_draws)

    Returns
    -------
    np.ndarray, same shape, with rank-normalized values
    """
    flat = x.ravel()
    n = len(flat)
    ranks = stats.rankdata(flat)
    z = stats.norm.ppf((ranks - 3 / 8) / (n + 1 / 4))
    return z.reshape(x.shape)


def _autocovariance(x):
    """Compute autocovariance using zero-padded FFT (biased estimator)."""
    n = len(x)
    x_centered = x - np.mean(x)
    fft_x = np.fft.fft(x_centered, n=2 * n)
    acov = np.fft.ifft(fft_x * np.conj(fft_x))[:n].real / n
    return acov


def _ess_core(chains):
    """Core ESS computation with initial positive sequence estimator.

    This is the base ESS algorithm applied to whatever chains are passed in
    (already split, rank-normalized, or indicator-transformed).

    Parameters
    ----------
    chains : np.ndarray, shape (n_chains, n_draws)

    Returns
    -------
    float : Effective sample size (minimum 1.0)
    """
    n_chains, n_draws = chains.shape

    # Per-chain autocovariance
    acov = np.array([_autocovariance(chains[i]) for i in range(n_chains)])
    mean_acov = np.mean(acov, axis=0)

    # Within-chain variance (W) and between-chain variance (B)
    W = np.mean(np.var(chains, axis=1, ddof=1))
    chain_means = np.mean(chains, axis=1)
    B = n_draws * np.var(chain_means, ddof=1)

    # Marginal posterior variance estimate (var_hat+)
    var_hat = ((n_draws - 1) / n_draws) * W + B / n_draws

    if var_hat < 1e-25:
        return float(n_chains * n_draws)

    # Autocorrelation estimates
    rho_hat = 1.0 - (W - mean_acov) / var_hat

    # Initial positive sequence estimator:
    # Group consecutive pairs P_k = rho(2k) + rho(2k+1)
    # Continue while P_k > 0
    sum_rho = 0.0
    t = 0
    while t < n_draws - 1:
        pair_sum = rho_hat[t] + rho_hat[t + 1]
        if pair_sum < 0:
            break
        sum_rho += pair_sum
        t += 2

    # Integrated autocorrelation time
    tau_hat = max(
        -1.0 + 2.0 * sum_rho, 1.0 / np.log10(max(n_chains * n_draws, 10))
    )
    ess = n_chains * n_draws / tau_hat
    return max(float(ess), 1.0)


def compute_rhat(chains):
    """Rank-normalized split-R-hat (Vehtari et al. 2021).

    1. Split each chain in half
    2. Rank-normalize the split chains
    3. Compute standard R-hat on the transformed values

    Parameters
    ----------
    chains : np.ndarray, shape (n_chains, n_draws)

    Returns
    -------
    float : R-hat statistic (values near 1.0 indicate convergence)
    """
    # Step 1: Split chains
    split = _split_chains(chains)

    # Step 2: Rank-normalize
    z = _rank_normalize(split)

    # Step 3: Compute R-hat on rank-normalized split chains
    n_chains, n_draws = z.shape
    W = np.mean(np.var(z, axis=1, ddof=1))
    chain_means = np.mean(z, axis=1)
    B = n_draws * np.var(chain_means, ddof=1)
    var_hat = ((n_draws - 1) / n_draws) * W + B / n_draws

    if W < 1e-25:
        return 1.0

    return float(np.sqrt(var_hat / W))


def compute_ess(chains):
    """Compute ESS with initial positive sequence estimator."""
    return _ess_core(chains)


def compute_bulk_ess(chains):
    """Bulk ESS on rank-normalized split chains.

    Measures sampling efficiency for the bulk of the distribution.

    Parameters
    ----------
    chains : np.ndarray, shape (n_chains, n_draws)

    Returns
    -------
    float : Bulk ESS
    """
    split = _split_chains(chains)
    z = _rank_normalize(split)
    return _ess_core(z)


def compute_tail_ess(chains):
    """Tail ESS using 5th/95th percentile indicator variables.

    Measures sampling efficiency in the tails. Computed as:
    min(ESS(I(x <= q_0.05)), ESS(I(x <= q_0.95)))
    where quantiles are from pooled split-chain draws.

    Parameters
    ----------
    chains : np.ndarray, shape (n_chains, n_draws)

    Returns
    -------
    float : Tail ESS
    """
    split = _split_chains(chains)
    pooled = split.ravel()
    q05 = np.quantile(pooled, 0.05)
    q95 = np.quantile(pooled, 0.95)

    I_low = (split <= q05).astype(float)
    I_high = (split <= q95).astype(float)

    ess_low = _ess_core(I_low)
    ess_high = _ess_core(I_high)

    return min(ess_low, ess_high)


def compute_mcse_mean(chains):
    """Monte Carlo Standard Error for the posterior mean.

    MCSE = posterior_sd / sqrt(bulk_ESS)

    Parameters
    ----------
    chains : np.ndarray, shape (n_chains, n_draws)

    Returns
    -------
    float : MCSE for the mean
    """
    pooled = chains.ravel()
    posterior_sd = np.std(pooled, ddof=1)
    bulk_ess = compute_bulk_ess(chains)
    return float(posterior_sd / np.sqrt(max(bulk_ess, 1.0)))


def compute_waic(log_lik):
    """Widely Applicable Information Criterion with numerical stability.

    Uses logsumexp for computing lppd and sample variance (ddof=1) for p_waic.

    Parameters
    ----------
    log_lik : np.ndarray, shape (n_chains, n_draws, n_obs)

    Returns
    -------
    dict : {'waic', 'lppd', 'p_waic', 'waic_se'}
    """
    n_chains, n_draws, n_obs = log_lik.shape
    pooled = log_lik.reshape(-1, n_obs)
    S = pooled.shape[0]

    # Log pointwise predictive density with logsumexp for numerical stability
    # lppd_i = log(1/S * sum_s exp(log_lik_{i,s}))
    #        = logsumexp(log_lik_{i,:}) - log(S)
    lppd_i = logsumexp(pooled, axis=0) - np.log(S)
    lppd = np.sum(lppd_i)

    # Effective number of parameters (sample variance, ddof=1)
    p_waic_i = np.var(pooled, axis=0, ddof=1)
    p_waic = np.sum(p_waic_i)

    # WAIC
    waic = -2 * (lppd - p_waic)

    # Standard error
    waic_i = -2 * (lppd_i - p_waic_i)
    waic_se = float(np.sqrt(n_obs * np.var(waic_i, ddof=1)))

    return {
        "waic": float(waic),
        "lppd": float(lppd),
        "p_waic": float(p_waic),
        "waic_se": waic_se,
    }


def generate_report(rhat_dict, bulk_ess_dict, tail_ess_dict, param_names):
    """Classify parameters as converged/marginal/failed.

    Criteria:
    - converged: R-hat < 1.01 AND bulk_ESS > 400 AND tail_ESS > 400
    - marginal:  R-hat < 1.05 AND bulk_ESS > 100 AND tail_ESS > 100
    - failed:    anything else

    Parameters
    ----------
    rhat_dict : dict - parameter name -> R-hat
    bulk_ess_dict : dict - parameter name -> bulk ESS
    tail_ess_dict : dict - parameter name -> tail ESS
    param_names : list of str

    Returns
    -------
    dict with keys 'converged', 'marginal', 'failed'
    """
    converged = []
    marginal = []
    failed = []

    for name in param_names:
        rhat = rhat_dict[name]
        bess = bulk_ess_dict[name]
        tess = tail_ess_dict[name]

        if rhat < 1.01 and bess > 400 and tess > 400:
            converged.append(name)
        elif rhat < 1.05 and bess > 100 and tess > 100:
            marginal.append(name)
        else:
            failed.append(name)

    return {"converged": converged, "marginal": marginal, "failed": failed}
