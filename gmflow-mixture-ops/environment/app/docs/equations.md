# Gaussian Mixture Operations — Mathematical Reference

## Notation

- **K** — number of mixture components
- **D** — data dimensionality
- **sigma** — shared isotropic standard deviation (scalar), stored as `log(sigma)` in the `logstds` tensor
- **mu_k in R^D** — mean of component k, stored in `means[:, k, :]`
- **w_k** — mixture weight, stored as `log(w_k)` in `logweights[:, k, :]`
- **x in R^D** — data sample

## 1. GM NLL Loss (without normalization constant)

    NLL(x) = -log sum_k exp(l_k)

where

    l_k = sum_{d=1}^{D} [ -1/2 * ((x_d - mu_{k,d}) / sigma)^2 - log(sigma) ] + log(w_k)

Use `torch.logsumexp` for numerical stability.
Clamp `1/sigma <= 1/eps` to avoid overflow when sigma is very small.

## 2. Moment-Matched Isotropic Gaussian

Given weights `w_k = exp(log w_k)` that sum to 1:

    mu_bar = sum_k  w_k * mu_k

    sigma_bar^2 = (1/D) * sum_k  w_k * ||mu_k - mu_bar||^2  +  sigma^2

The first term is the between-component variance **averaged over dimensions** D.
The second term is the within-component variance.

Output: mean (bs, D), var (bs, 1).

## 3. GM x Isotropic Gaussian Product

Compute the product `p(x)^a * q(x)^b` where `p` is the GM and `q = N(mu_q, sigma_q^2 * I)`.

Define:
- `r = b / a` (power ratio — note: **b over a**, i.e., gaussian_power / gm_power)
- `nu = sigma_q^2 + r * sigma^2` (normalization factor)

Updated means:

    mu'_k = (sigma_q^2 * mu_k  +  r * sigma^2 * mu_q) / nu

Updated log-std:

    log(sigma') = log(sigma) + log(sigma_q) - 1/2 * log(nu)

where `log(sigma_q) = 1/2 * log(sigma_q^2) = 1/2 * log(var_q)`.

Updated log-weights:

    Delta_k = -(r / (2 * nu)) * ||mu_k - mu_q||^2

    log(w'_k) = log_softmax_k( log(w_k) + Delta_k )

## 4. GM Log Probability (with normalization)

    log p(x) = log sum_k exp(l_tilde_k)

where

    l_tilde_k = l_k + const

    const = -(D/2) * log(2*pi)

and `l_k` is as defined in section 1 (evaluated at each sample separately when
multiple samples are provided).

## 5. GM x GM Product

Product of two Gaussian mixtures:

    p(x) = sum_{i=1}^{K1} w1_i * N(x; mu1_i, sigma1^2 * I)
    q(x) = sum_{j=1}^{K2} w2_j * N(x; mu2_j, sigma2^2 * I)

The product p(x) * q(x) is a GM with K1 * K2 components. For each pair (i, j):

Define:
- `nu = sigma1^2 + sigma2^2` (sum of variances)

New mean:

    mu'_{ij} = (sigma2^2 * mu1_i + sigma1^2 * mu2_j) / nu

New shared log-std:

    log(sigma') = log(sigma1) + log(sigma2) - 1/2 * log(nu)

Weight update:

    Delta_{ij} = -||mu1_i - mu2_j||^2 / (2 * nu)

    log(w'_{ij}) = log_softmax_{ij}( log(w1_i) + log(w2_j) + Delta_{ij} )

The K1*K2 output components are flattened into a single component dimension
with ordering (i=0,j=0), (i=0,j=1), ..., (i=K1-1,j=K2-1).

## 6. GM KL Divergence (Monte Carlo)

    KL(p || q) ≈ (1/N) * sum_{n=1}^{N} [log p(x_n) - log q(x_n)]

where x_n ~ p(x), using `gm_logprob` for both log p and log q.
Sampling from p is done by first selecting a component index from the mixture
weights, then sampling from the selected Gaussian component.

## 7. GM Component Reduction

Given a GM with K components, produce an approximation with K' < K components
that minimizes the loss of information.

**Hard constraints** on the reduced mixture:
- Must have exactly K' components
- Weights must be properly normalized (sum to 1)
- The shared isotropic log-std must be preserved (unchanged from the original)
- The mean of the reduced mixture must equal the mean of the original:

      sum_k  w'_k * mu'_k  =  sum_k  w_k * mu_k

  (This is the moment-matching condition on the first moment.)

**Quality constraint**:
- The KL divergence KL(original || reduced) should be small (bounded).

**Merge operation**: When two components i and j are combined into one:

    w' = w_i + w_j

    mu' = (w_i * mu_i  +  w_j * mu_j) / (w_i + w_j)

Note that this merge operation preserves the first moment exactly.

**No specific reduction algorithm is prescribed.** The choice of which components
to merge and in what order is a design decision. A good strategy should minimize
the total information loss across all merge steps.
