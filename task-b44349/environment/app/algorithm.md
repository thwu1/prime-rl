# Score Functions for Gaussian Mixture Distributions

## Notation

A Gaussian mixture (GM) distribution in D dimensions with K components:

    p(x) = sum_{k=1}^{K}  pi_k  N(x; mu_k, sigma^2 I_D)

where pi_k = softmax(w)_k are the mixing weights (with raw log-weights w_k),
mu_k in R^D are the component means, and sigma^2 is a shared isotropic variance
(sigma = exp(logstd)).


## Responsibilities

The posterior component membership probability of component k at point x:

    psi_k(x) = pi_k N(x; mu_k, sigma^2 I) / p(x)

Satisfies sum_k psi_k(x) = 1 for all x.

**Numerical consideration**: Computing psi_k requires evaluating N(x; mu_k, sigma^2 I),
which underflows to zero in floating-point when ||x - mu_k||^2 >> sigma^2. A robust
implementation must compute responsibilities entirely in log-space using the log-sum-exp
trick to avoid the 0/0 failure mode.


## Score Function

The score function is the gradient of the log-density:

    s(x) = grad_x log p(x) = sum_k psi_k(x) * s_k(x)

where s_k(x) = -(x - mu_k) / sigma^2 is the score of the k-th component.

The score is a responsibility-weighted average of per-component scores.


## Score Divergence (Laplacian of log p)

The divergence of the score function equals the Laplacian of log p:

    div s(x) = Tr(Hessian log p(x))

For a GM with shared isotropic variance, this decomposes as:

    div s(x) = sum_k psi_k(x) ||s_k(x)||^2  -  ||s(x)||^2  -  D / sigma^2

The first two terms represent the responsibility-weighted variance of per-component
scores: Var_psi[s_k] = E_psi[||s_k||^2] - ||E_psi[s_k]||^2.

### Derivation sketch

Starting from s = (1/p) grad p = sum_k psi_k s_k, apply the product rule:

    div s = sum_k [grad psi_k . s_k  +  psi_k div s_k]

Using div s_k = -D/sigma^2 and the identity grad psi_k = psi_k (s_k - s):

    div s = sum_k psi_k (||s_k||^2 - s . s_k  -  D/sigma^2)
          = E_psi[||s_k||^2] - ||s||^2 - D/sigma^2


### Stein Identity

For any distribution p with score s:

    E_{x ~ p}[ div s(x) + ||s(x)||^2 ] = 0

This identity links the score and its divergence and can serve as a verification
condition: if an implementation satisfies the Stein identity (up to Monte Carlo noise),
the score and divergence are mutually consistent.


## Kernel Stein Discrepancy (KSD)

The KSD measures discrepancy between a distribution p (specified by its score s_p) and
an empirical distribution q_n = (1/n) sum_i delta(x_i):

    KSD^2(p, q_n) = (1/n^2) sum_{i=1}^n sum_{j=1}^n  u_p(x_i, x_j)

where the Stein kernel u_p is:

    u_p(x, y) = s(x)^T s(y) k(x,y)
              + s(x)^T grad_y k(x,y)
              + s(y)^T grad_x k(x,y)
              + Tr(grad_x grad_y k(x,y))

### IMQ Kernel

Use the inverse multiquadric (IMQ) kernel with exponent beta = 1/2:

    k(x, y) = (c^2 + ||x - y||^2)^{-1/2}

The required derivatives (with r^2 = ||x - y||^2):

    grad_x k(x,y) = -(c^2 + r^2)^{-3/2} (x - y)

    grad_y k(x,y) =  (c^2 + r^2)^{-3/2} (x - y)

    Tr(grad_x grad_y k) = D (c^2 + r^2)^{-3/2}  -  3 r^2 (c^2 + r^2)^{-5/2}

Equivalently: Tr(grad_x grad_y k) = (c^2 + r^2)^{-5/2} [D c^2 + (D - 3) r^2]

### Bandwidth Selection

If no bandwidth c is provided, use the median heuristic:

    c^2 = median({ ||x_i - x_j||^2  :  1 <= i < j <= n })
