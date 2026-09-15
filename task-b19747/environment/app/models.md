# Statistical Models for Posterior Inference

## Model 1: Eight Schools (Hierarchical Normal)

A non-centered hierarchical model for J=8 schools' treatment effect estimates.

### Data (`/app/data/eight_schools.json`)
- `J`: number of schools (8)
- `y[j]`: observed treatment effect for school j
- `sigma[j]`: known standard error for school j

### Parameters
- `mu` ∈ ℝ: overall mean effect
- `tau` ∈ ℝ₊ (positive real): between-school standard deviation
- `theta_tilde[j]` ∈ ℝ for j=1..J: standardized school effects

### Transformed Parameters
- `theta[j] = mu + tau * theta_tilde[j]` for j=1..J

### Prior
- `mu ~ Normal(0, 5)` — i.e., Normal with mean 0 and standard deviation 5
- `tau ~ HalfCauchy(0, 5)` — i.e., Cauchy(0, 5) truncated to τ > 0
- `theta_tilde[j] ~ Normal(0, 1)` independently for j=1..J

### Likelihood
- `y[j] ~ Normal(theta[j], sigma[j])` independently for j=1..J

### Output parameters (18 total)
`mu`, `tau`, `theta_tilde[1]` through `theta_tilde[8]`, `theta[1]` through `theta[8]`

---

## Model 2: GP Regression (Gaussian Process)

A Gaussian process regression model with squared exponential (exponentiated quadratic) kernel.

### Data (`/app/data/gp_regr.json`)
- `N`: number of observations (11)
- `x[i]`: input locations (real-valued)
- `y[i]`: observed output values

### Parameters (all positive reals)
- `rho` ∈ ℝ₊: length scale
- `alpha` ∈ ℝ₊: marginal standard deviation (signal amplitude)
- `sigma` ∈ ℝ₊: observation noise (added directly to diagonal of covariance)

### Covariance Matrix
`K[i,j] = alpha² * exp(-0.5 * (x[i] - x[j])² / rho²) + sigma * δ(i,j)`

where δ(i,j) is the Kronecker delta. Note: `sigma` (not `sigma²`) is added to the diagonal.

### Prior
- `rho ~ Gamma(shape=25, rate=4)` — mean = 25/4 = 6.25
- `alpha ~ HalfNormal(0, 2)` — Normal(0, σ=2) truncated to α > 0
- `sigma ~ HalfNormal(0, 1)` — Normal(0, σ=1) truncated to σ > 0

### Likelihood
- `y ~ MultivariateNormal(0, K)` — zero-mean GP with covariance K

### Output parameters (3 total)
`rho`, `alpha`, `sigma`

---

## Model 3: SIR Epidemiological Model

A susceptible-infected-recovered model with waterborne bacteria dynamics, requiring numerical ODE integration.

### Data (`/app/data/sir.json`)
- `N_t`: number of observation time points (20)
- `t[n]`: observation times (n=1..N_t)
- `y0[4]`: initial conditions [S₀, I₀, R₀, B₀]
- `stoi_hat[n]`: observed new infection counts at time n
- `B_hat[n]`: observed bacteria concentrations at time n

### Parameters (all positive reals)
- `beta` ∈ ℝ₊: water contact rate
- `gamma` ∈ ℝ₊: recovery rate
- `xi` ∈ ℝ₊: bacteria production rate
- `delta` ∈ ℝ₊: bacteria removal rate

### Fixed Constants
- `kappa = 1000000`: C₅₀ half-saturation constant

### ODE System
Integrate from t₀ = 0 with initial state y₀:

```
dS/dt = -beta * B / (B + kappa) * S
dI/dt =  beta * B / (B + kappa) * S - gamma * I
dR/dt =  gamma * I
dB/dt =  xi * I - delta * B
```

State vector: y = [S, I, R, B]. Evaluate at observation times t[1..N_t].

### Prior
- `beta ~ HalfCauchy(0, 2.5)` — Cauchy(0, 2.5) truncated to β > 0
- `gamma ~ HalfCauchy(0, 1)`
- `xi ~ HalfCauchy(0, 25)`
- `delta ~ HalfCauchy(0, 1)`

### Likelihood
- `stoi_hat[1] ~ Poisson(y0[1] - y[1, S])` — new infections in first period (S decreases)
- `stoi_hat[n] ~ Poisson(y[n-1, S] - y[n, S])` for n=2..N_t
- `B_hat[n] ~ Lognormal(log(y[n, B]), 0.15)` for n=1..N_t

where y[n, S] is the susceptible count at time t[n] and y[n, B] is the bacteria count.

### Output parameters (84 total)
`beta`, `gamma`, `xi`, `delta`, `y[1,1]` through `y[20,4]`

The `y[n,j]` notation uses 1-indexed: n=1..20 (time points), j=1..4 (state variables: S, I, R, B).
