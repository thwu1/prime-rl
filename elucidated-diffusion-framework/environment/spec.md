# Generalized Sigma-Parameterized Diffusion Framework — Mathematical Specification

This document specifies a generalized sigma-parameterized diffusion framework
that extends standard preconditioning with a configurable exponent α,
tanh-compressed noise conditioning, a log-cosine sigma schedule, and a modified
DPM++ second-order correction coefficient.

All section numbers correspond to method docstrings in `diffusion.py`.

## 1. Notation

| Symbol | Meaning |
|--------|---------|
| σ | Noise level (sigma) |
| σ\_data | Standard deviation of the data distribution (hyperparameter) |
| σ\_min, σ\_max | Minimum and maximum noise levels |
| α | Preconditioning exponent (hyperparameter, default 3) |
| P\_mean, P\_std | Mean and std of the log-normal training noise distribution |
| S\_churn, S\_tmin, S\_tmax, S\_noise | Stochastic sampling parameters |
| F\_θ | Raw neural network (UNet) |
| D(x; σ) | Preconditioned denoiser output |

## 2. Preconditioning Functions

The framework defines four preconditioning coefficients parameterized by the
generalized exponent α:

**Skip connection coefficient:**

    c_skip(σ) = σ_data^α / (σ^α + σ_data^α)

**Output scaling coefficient:**

    c_out(σ) = σ · σ_data / (σ^α + σ_data^α)^(1/α)

**Input scaling coefficient:**

    c_in(σ) = (σ^α + σ_data^α)^(−1/α)

**Noise conditioning (passed to the network as its time input):**

    c_noise(σ) = tanh( ln(σ) / 4 )

Use `torch.tanh` for the hyperbolic tangent and the numerically stable `log`
function from `helpers.py` for the logarithm.

## 3. Preconditioned Denoiser Output

The preconditioned denoiser combines a skip connection with the scaled network
output:

    D(x; σ) = c_skip(σ) · x + c_out(σ) · F_θ(c_in(σ) · x, c_noise(σ))

Implementation notes:
- When σ is a Python float, expand it to a tensor of shape (B,) matching the
  batch size.
- For element-wise operations with images of shape (B, C, H, W), reshape σ to
  (B, 1, 1, 1) so it broadcasts correctly. Use this "padded" sigma for c_skip,
  c_out, and c_in.
- For the noise conditioning input to the network, keep σ as shape (B,) — the
  network's internal MLP handles the 1D input.
- The network call is: `net(c_in(σ_padded) * x, c_noise(σ), self_cond)`
- If `clamp=True`, clamp the final output to [-1, 1].

## 4. Noise Schedule for Sampling

The schedule uses log-cosine interpolation to define N+1 decreasing sigma
values. For i = 0, ..., N−1, compute:

    w_i = (1 − cos(π · i / (N−1))) / 2

    σ_i = exp( (1 − w_i) · ln(σ_max) + w_i · ln(σ_min) )

The final value σ\_N = 0 is appended (padding). The result is a 1D tensor of
length N+1 on the model's device.

Note: this is a cosine interpolation in log-space. At i=0 we get σ\_max, and at
i=N−1 we get σ\_min. The cosine weighting concentrates sigma values near the
extremes, producing the geometric mean σ = √(σ\_max · σ\_min) at the midpoint.

Use `math.pi` and `math.log` (Python standard library) for the constants, and
`torch.cos` and `torch.exp` for tensor operations.

## 5. Training

### 5.1 Noise Distribution

Training noise levels are sampled from a log-normal distribution:

    σ ~ exp(𝒩(P_mean, P_std²))

Concretely: sample z ~ 𝒩(P\_mean, P\_std²) and return exp(z).
The result is a (B,) tensor of positive noise levels.

### 5.2 Loss Weight

    λ(σ) = (σ^α + σ_data^α)^(2/α) · (σ · σ_data)^(−2)

### 5.3 Training Forward Pass

Given clean images in [0, 1]:

1. Normalize to [-1, 1]: x = 2·images − 1
2. Sample noise levels σ ~ noise\_distribution(B)
3. Sample noise: ε ~ 𝒩(0, I), same shape as x
4. Create noisy images: x\_noisy = x + σ · ε   (σ reshaped to (B,1,1,1))
5. (Optional self-conditioning) With probability 0.5:
   - Compute detached estimate: x̂ = D(x\_noisy; σ).detach()
   - This becomes the self\_cond argument for the actual forward pass
6. Compute denoised: D(x\_noisy; σ, self\_cond)
7. Per-sample MSE: L\_i = mean over (C,H,W) of (D − x)²
8. Weighted loss: L\_i = L\_i · λ(σ\_i)
9. Return mean over batch: L = mean(L)

## 6. Stochastic Sampling (Heun's Method)

This sampler uses Heun's second-order method with optional stochastic noise
injection.

### 6.1 Setup

1. Compute sigma schedule: {σ\_0, ..., σ\_N} (Section 4)
2. Compute per-step stochasticity:

       γ_i = min(S_churn / N, √2 − 1)   if S_tmin ≤ σ_i ≤ S_tmax
       γ_i = 0                            otherwise

3. Pair consecutive sigmas: (σ\_i, σ\_{i+1}, γ\_i) for i = 0..N−1
4. Initialize: x = σ\_0 · ε,  where ε ~ 𝒩(0, I)

### 6.2 Main Loop

For each step (σ, σ\_next, γ):

**(a) Stochastic noise injection:**

    σ̂ = σ + γ · σ
    x̂ = x + √(σ̂² − σ²) · S_noise · ε     (ε ~ 𝒩(0, I))

**(b) First-order Euler step:**

    d₁ = (x̂ − D(x̂; σ̂)) / σ̂
    x_next = x̂ + (σ_next − σ̂) · d₁

**(c) Second-order Heun correction** (only if σ\_next ≠ 0):

    d₂ = (x_next − D(x_next; σ_next)) / σ_next
    x_next = x̂ + (σ_next − σ̂) · (d₁ + d₂) / 2

**(d) Update:**

    x ← x_next

### 6.3 Self-conditioning in sampling

When self\_condition is enabled, pass the previous step's denoised model output
as self\_cond to the current step's denoiser call. For the first step, self\_cond
is None. For the second-order correction denoiser call, use the first-order
denoised output as self\_cond.

### 6.4 Output

Clamp final x to [-1, 1], then unnormalize to [0, 1].

## 7. DPM++ Second-Order Multistep Sampler (Modified)

An alternative sampler based on the DPM-Solver++ framework using a modified
second-order multistep method with a damped correction coefficient. This sampler
does NOT use self-conditioning or stochastic noise.

### 7.1 Space Conversions

Define mappings between sigma-space and t-space:

    t(σ) = −ln(σ)
    σ(t) = exp(−t)

### 7.2 Algorithm

1. Initialize: x = σ\_0 · ε,  ε ~ 𝒩(0, I)
2. Set D\_prev = None

3. For each step i = 0, ..., N−1:

   (a) Compute denoised estimate: D\_i = D(x; σ\_i)

   (b) Convert to t-space:
       t\_i = t(σ\_i),   t\_{i+1} = t(σ\_{i+1})
       h = t\_{i+1} − t\_i

   (c) Compute effective denoised output:
       - If i = 0 or σ\_{i+1} = 0:
             D\_eff = D\_i                         (first-order)
       - Otherwise (second-order correction with damping):
             h\_prev = t\_i − t(σ\_{i-1})
             r = h\_prev / h
             γ = −1 / (2r + r²)
             D\_eff = (1 − γ) · D\_i + γ · D\_prev

   (d) Update x:
       x = (σ(t\_{i+1}) / σ(t\_i)) · x − expm1(−h) · D\_eff

       where expm1(z) = exp(z) − 1.

       Note: compute expm1(−h) via `(-h).expm1()` for numerical stability.

   (e) Store D\_prev = D\_i for next iteration

4. Clamp x to [-1, 1], unnormalize to [0, 1].
