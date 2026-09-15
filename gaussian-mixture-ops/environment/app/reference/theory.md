# Gaussian Mixture Operations — Mathematical Reference

This document provides the mathematical formulations for the Gaussian
Mixture (GM) operations you need to implement.  All formulas follow the
conventions of the GMFlow paper (arXiv 2504.05304).

## 1. Representation

A K-component isotropic Gaussian Mixture in D dimensions:

    p(x) = sum_{k=1}^{K} w_k * N(x; mu_k, sigma^2 I)

Stored as:
- `means`      (bs, K, D)  — component means mu_k
- `logstds`    (bs, 1, 1)  — log(sigma), shared across components and dims
- `logweights` (bs, K, 1)  — unnormalized log w_k

Normalized weights: w_k = softmax(logweights)_k.
Component variance:  sigma^2 = exp(2 * logstd).

---

## 2. NLL Loss (gm_nll_loss)

Training loss that drops the constant -D/2 log(2 pi).

    inv_sigma = exp(-logstd),  clamped to [0, 1/eps]
    diff_weighted_{k,d} = (x_d - mu_{k,d}) * inv_sigma

    gaussian_ll_k = sum_d [ -0.5 * diff_weighted_{k,d}^2 - logstd ]

    NLL(x) = -logsumexp_k [ gaussian_ll_k + logweight_k ]

Input shape: samples (bs, D).  Output shape: (bs,).

---

## 3. Isotropic Gaussian Approximation (gm_to_iso_gaussian)

Moment-match a GM to N(mu_g, sigma_g^2 I):

    w_k   = softmax(logweights)_k          (bs, K, 1)
    mu_g  = sum_k w_k * mu_k              (bs, D)

    diffs_k = mu_k - mu_g                 (bs, K, D)
    spread  = sum_k w_k * diffs_k^2       (bs, D)      [weighted variance per dim]

    sigma_g^2 = mean_d(spread) + sigma_GM^2

where sigma_GM^2 = exp(2 * logstd).

Note:  `sum_k` is weighted sum over components (dim 1);  `mean_d` is
arithmetic mean over dimensions (last dim).

Output: dict  mean (bs, D),  var (bs, 1).

---

## 4. GM x Isotropic Gaussian (gm_mul_iso_gaussian)

Product of a GM raised to power alpha with an isotropic Gaussian raised
to power beta:

    p(x) proportional to GM(x)^alpha * N(x; mu_g, sigma_g^2 I)^beta

Define:
    r = beta / alpha                             (power ratio)
    F = sigma_g^2 + r * sigma_GM^2               (norm factor, clamp >= eps)

Updated GM parameters:

    new_mu_k    = ( sigma_g^2 * mu_k  +  r * sigma_GM^2 * mu_g ) / F
    new_logstd  = logstd_GM + logstd_g - 0.5 * log(F)
    delta_k     = -0.5 * r * sum_d (mu_k - mu_g)_d^2  /  F
    new_logweight_k = log_softmax_k ( logweight_k + delta_k )

Here logstd_g = 0.5 * log(sigma_g^2), and sum_d is over dimensions
(keep the result as (bs, K, 1) by summing dim=-1 with keepdim).

Return (new_gm, alpha).

---

## 5. Full Log-Probability (gm_logprob)

Includes the -D/2 log(2 pi) constant (needed for correct KL estimation):

    const = -D/2 * log(2*pi)

    For each sample n and component k:
        diff_{n,k,d} = x_{n,d} - mu_{k,d}
        inv_sigma = exp(-logstd)
        diff_scaled = diff * inv_sigma

        gaussian_logprob_{n,k} = -0.5 * sum_d diff_scaled^2
                                 - D * logstd + const

    logprob_n = logsumexp_k [ logweight_k + gaussian_logprob_{n,k} ]

Input: samples (bs, N, D).
Output: logprob (bs, N), gaussian_logprobs (bs, N, K).

Broadcasting hint: expand samples to (bs, N, 1, D) and means to
(bs, 1, K, D) to compute pairwise differences (bs, N, K, D).

---

## 6. KL Divergence — Monte Carlo (gm_kl_div)

    KL(p || q) = E_p[ log p(x) - log q(x) ]
              approx (1/N) sum_i [ logprob_p(x_i) - logprob_q(x_i) ]

where x_i ~ p (drawn with gm_to_sample) and log-probs are evaluated
with gm_logprob.

Output shape: (bs,).

---

## 7. C Extension — Batch Log-PDF (gm_logpdf_c)

The C function gm_logpdf_batch computes the same quantity as gm_logprob
but for a single batch element, using double precision, operating on
raw C arrays loaded via ctypes.

    For each sample n (0 <= n < N):
        For each component k (0 <= k < K):
            sq = sum_{d=0}^{D-1} [ (samples[n,d] - means[k,d]) * exp(-logstd) ]^2
            term_k = logweight_k + (-0.5 * sq - D * logstd + const)
        output[n] = logsumexp_k ( term_k )

where const = -D/2 * log(2*pi) and logweight_k is used directly
(unnormalized, matching the Python gm_logprob convention).

The C implementation must use the log-sum-exp trick: find the maximum,
subtract it, exponentiate, sum, take the log, add the maximum back.

Array layout: row-major.  samples is (N, D), means is (K, D),
logweights is (K,).

---

## Numerical Stability Notes

- Always use logsumexp instead of log(sum(exp(...))).
- Clamp inverse_stds = exp(-logstds) to avoid overflow when logstds is
  very negative (tight components).
- When computing gm_mul_iso_gaussian, clamp the normalization factor F
  to at least eps to prevent division by zero.
- The log_softmax function is numerically stable by default in PyTorch.
