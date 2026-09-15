# Unbiased MCMC with Couplings: Mathematical Specification

This document specifies the algorithms to implement in `/app/couplings/`.

All notation follows Jacob, O'Leary, and Atchadé (2017) "Unbiased Markov
chain Monte Carlo with couplings" and Biswas and Jacob (2019) "Estimating
Convergence of Markov chains with L-Lag Couplings."

---

## 1. Background

MCMC produces asymptotically unbiased estimators. By running two chains
with a **coupling** construction — a joint distribution over (X, Y)
such that X ~ p and Y ~ q marginally — we can remove bias exactly
and estimate convergence diagnostics from **meeting times**.

A **maximal coupling** maximises P(X = Y). When p = q, a maximal coupling
gives X = Y with probability 1.

---

## 2. Vectorized Maximal Coupling

`maximal_coupling(rv1, rv2, size) -> (samples, cost)`

Given scipy.stats distribution objects rv1 (pdf p) and rv2 (pdf q),
draw `size` coupled pairs in a vectorized batch.

**Algorithm:**

1. Draw X_1, ..., X_n  i.i.d. from p  (`rv1.rvs(size=size)`).
2. Copy: set Y_i = X_i for all i. Set cost_i = 1.
3. For each i, draw U_i ~ Uniform(0, p(X_i)). Mark i for resampling
   if U_i > q(X_i).  (Use `np.random.uniform(0, p(X))` element-wise.)
4. While any indices remain marked:
   a. Increment cost_i for each marked i.
   b. Draw Y_i ~ q for each marked i  (`rv2.rvs(size=n_marked)`).
   c. For each still-marked i, draw V_i ~ Uniform(0, q(Y_i)).
      If V_i < p(Y_i), **keep** i marked (resample again).
      Otherwise unmark i (accept Y_i).
5. Return `np.vstack((X, Y)).T` of shape (size, 2), and cost array.

**Key properties:**
- When p = q: every sample couples immediately, cost = 1.
- When supports are disjoint: no coupling, cost = 2.

---

## 3. Reflection Maximal Coupling

`ReflectionMaximalCoupling(base_distribution, proposal_cov)`

For sampling coupled pairs X ~ N(mu1, Sigma) and Y ~ N(mu2, Sigma)
where the samples are **correlated even when not equal** (unlike the
basic maximal coupling which produces independent non-equal draws).

Uses a base distribution s (typically N(0, I_d)) and the Cholesky
factor of the proposal covariance.

### Initialisation (`__init__`)

- Compute L = cholesky(atleast_2d(proposal_cov))   [store as self.cholesky]
- Store base_distribution and dim = L.shape[0]

### Sampling (`__call__(mu1, mu2, chains)`)

1. If mu1 (or mu2) has shape (dim,) or is a scalar, tile to (chains, dim).
2. Compute the transformed difference:
       z = L^{-1} (mu1 - mu2)^T   then transpose to shape (chains, dim).
   Use `np.linalg.solve(L, (mu1 - mu2).T).T` on the atleast_2d result.
3. Draw base samples:  e ~ s  of shape (chains, dim).
   Use `s.rvs(size=chains).reshape((chains, dim))`.
4. Set tentative coupled draw: e' = e + z.
5. Log acceptance ratio (per chain):
       r_i = log s(e_i + z_i) - log s(e_i)
   Reshape to (chains,).
6. Draw U_1, ..., U_chains ~ Uniform(0,1).
   Accept coupling where log(U_i) < r_i.
7. For non-coupled chains, apply **Householder reflection**:
   - Unit direction: z_hat_i = z_i / ||z_i||
   - Reflected draw: e'_i = e_i - 2 * (e_i . z_hat_i) * z_hat_i
   Use `np.expand_dims` on the dot-product for correct broadcasting.
8. Return:
       X = mu1 + L @ e^T   (transposed to (chains, dim))
       Y = mu2 + L @ e'^T  (transposed to (chains, dim))

**Key properties:**
- When mu1 = mu2: z = 0, r = 0, log(U) < 0 always, so X = Y.
- When mu1 << mu2 (1D): reflection gives e' ≈ -e, so Y ≈ mu2 - e while X ≈ mu1 + e.

---

## 4. Coupled Metropolis-Hastings

`metropolis_hastings(*, log_prob, proposal_cov, init_x, init_y, lag, iters, chains, short_circuit) -> CoupledData`

### Data Structure

```
CoupledData(
    x:            shape (iters, chains, dim),
    y:            shape (iters - lag, chains, dim),
    x_accept:     shape (iters, chains),      dtype bool,
    y_accept:     shape (iters - lag, chains), dtype bool,
    meeting_time: shape (chains,),             init to -1,
    lag, iters, dim, chains
)
```

### Algorithm

**Setup:**
1. `proposal_cov = np.atleast_2d(proposal_cov)`,  `dim = proposal_cov.shape[0]`.
2. Allocate CoupledData arrays.
3. Tile init_x, init_y to (chains, dim) if they are vectors or scalars.
4. Set data.x[0] = init_x, data.y[0] = init_y.
5. Compute x_log_prob = log_prob(init_x), y_log_prob = log_prob(init_y).
   Wrap with `np.atleast_1d`.

**Phase 1 — Uncoupled (steps 1 to lag):**
6. Pre-generate proposals: `samples ~ N(0, proposal_cov)` of shape `(lag, chains, dim)`.
   Use `np.random.multivariate_normal(zeros(dim), proposal_cov, size=(lag, chains))`.
7. For idx = 1, 2, ..., lag (iterate over samples with enumerate starting at 1):
   - x_proposal = samples[idx-1] + data.x[idx-1]
   - (data.x[idx], x_log_prob, data.x_accept[idx]) = _metropolis_accept(log_prob, x_proposal, data.x[idx-1], x_log_prob)

**Phase 2 — Coupled (steps lag+1 to iters-1):**
8. Create `base_distribution = multivariate_normal(zeros(dim), eye(dim))`.
9. Create `rmc = ReflectionMaximalCoupling(base_distribution, proposal_cov)`.
10. Pre-generate shared log-uniforms: `log_unifs = log(rand(iters - lag - 1, chains))`.
11. For each (t, log_unif) in enumerate(log_unifs, start=lag+1):
    a. Generate coupled proposals:
       `(x_proposal, y_proposal) = rmc(data.x[t-1], data.y[t-lag-1], chains)`
    b. X chain acceptance (with shared uniform):
       `(data.x[t], x_log_prob, data.x_accept[t]) = _metropolis_accept(log_prob, x_proposal, data.x[t-1], x_log_prob, log_unif)`
    c. Y chain acceptance (with **same** shared uniform):
       `(data.y[t-lag], y_log_prob, data.y_accept[t-lag]) = _metropolis_accept(log_prob, y_proposal, data.y[t-lag-1], y_log_prob, log_unif)`
    d. Meeting detection:
       `met = np.isclose(data.x[t], data.y[t-lag])`
       Reshape met to (chains, -1) and require all dimensions to match: `.all(axis=1)`.
    e. Record first meeting:
       `data.meeting_time[met & (data.meeting_time < 0)] = t + 1`
    f. Short circuit: if `short_circuit and met.all()`:
       Truncate `data.x = data.x[:t+1]`, `data.y = data.y[:t-lag+1]`,
       similarly for x_accept and y_accept. Set `data.iters = t + 1`. Return.

Return data.

**Critical detail:** Both chains use the **same** log_unif for the
Metropolis acceptance. This ensures that when the proposals are equal
(after meeting), the acceptance decisions are identical, and the chains
remain coupled forever.

---

## 5. Unbiased Estimator (Equation 2.1)

`unbiased_estimator(data, func, burn_in) -> (mcmc_average, bias_correction)`

Given CoupledData with X of shape (n, C, d), Y of shape (n-L, C, d),
meeting times tau of shape (C,), test function h, and burn-in k.

**Definitions:**
- normalizer = n - k + 1
- T = n  if any tau_c == -1 (chain never met), else max(tau) + 1

**MCMC Average:**

    mcmc_avg = sum_{t=k}^{n-1} h(X_t) / normalizer

Sum h(X_t) over the time axis from index k to end. Shape: (C, d).

**Bias Correction:**

For each time index t in {k+1, k+2, ..., T-2}:

1. weight_t = min(1, (t - k) / normalizer)
2. delta_t = h(X_t) - h(Y_{t-L})        shape: (C, d)
3. For each chain c: if t > tau_c, set delta_{t,c} = 0

    bias_corr = sum_t weight_t * delta_t

Shape: (C, d).

**Implementation hints:**
- Create time index array: `slicer = np.arange(k+1, T-1)`.
- Tile slicer to (len(slicer), C) for per-chain comparison.
- Compute ratio = min(1, (slicer - k) / normalizer).
- Compute mult = h(X[slicer]) - h(Y[slicer - L]).
- Zero out: mult[time_indices > tau] = 0.
- Weight and sum: bias_corr = sum(expand_dims(ratio, -1) * mult, axis=0).

**Return:** (mcmc_avg, bias_corr). Their sum is the unbiased estimate.

---

## 6. Convergence Diagnostics

### Pointwise TV indicator (helper)

For chain c at iteration t (0-indexed):

    TV_c(t) = max(0,  ceil( (tau_c - L - t) / L ))

where tau_c is the meeting time (1-indexed), L is the lag.

Use broadcasting: expand meeting_time to (C, 1), subtract arange(n) to
get shape (C, n).

### Total Variation Distance Bound

`total_variation(data) -> array of shape (n,)`

    TV(t) = (1/C) sum_c TV_c(t)

Average the pointwise indicator over chains (axis 0).

### Wasserstein-1 Distance Bound

`wasserstein(data) -> array of shape (n,)`

For each time index t:

    W(t) = (1/C) sum_c  sum_{j=1}^{K_c(t)}  ||X_{t + j*L, c} - Y_{t + (j-1)*L, c}||_1

where K_c(t) = TV_c(t) is the number of "hops" for chain c.

**Implementation:**
1. Transpose the pointwise TV matrix to shape (n, C), cast to int.
2. For each row index `idx` (time step):
   - Initialise expect = zeros(C).
   - For j = 1, 2, ..., max(row):
     - Select chains where row[c] >= j.
     - Accumulate: expect[selected] += |X[idx + j*L, selected] - Y[idx + (j-1)*L, selected]|
       summed over the last axis (dimensions).
   - wass[idx] = mean(expect).
3. Return wass.

**Key property:** W(t) = 0 for all t >= max(tau) - L.
