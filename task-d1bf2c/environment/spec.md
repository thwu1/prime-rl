# EKF-Based Probabilistic ODE Solver Specification

## Problem

Given an initial value problem y'(t) = f(y(t)), y(t_0) = y_0, solve it using
an Extended Kalman Filter (EKF) with an Integrated Wiener Process (IWP) prior.
The solver produces a posterior Gaussian distribution over the ODE solution,
including calibrated uncertainty estimates.

## State Representation

The IWP(q) prior models derivatives up to order q. For a d-dimensional ODE:

**State vector** (dimension N = d(q+1)):

    x = [y_1, ..., y_d, y_1', ..., y_d', ..., y_1^(q), ..., y_d^(q)]

Components are grouped by derivative order: all d spatial components of the
k-th derivative occupy indices [k*d, (k+1)*d).

## IWP(q) Transition and Process Noise

For step size h, the scalar (q+1) x (q+1) matrices are:

**Transition matrix** (upper triangular Pascal matrix):

    A(h)_{ij} = h^(j-i) / (j-i)!     for j >= i     (0-indexed)
    A(h)_{ij} = 0                      for j < i

**Process noise covariance** (unit diffusion sigma^2 = 1):

    Q(h)_{ij} = h^(2q-i-j+1) / [ (q-i)! * (q-j)! * (2q-i-j+1) ]     (0-indexed)

The full N x N matrices use Kronecker products with the d x d identity:

    A_full(h) = A(h) (kron) I_d
    Q_full(h) = sigma^2 * [ Q(h) (kron) I_d ]

where sigma^2 is the output diffusion parameter.

## Extraction Matrices

    E_0: d x N matrix, extracts y (derivative 0): E_0[i, i] = 1 for i = 0, ..., d-1
    E_1: d x N matrix, extracts y' (derivative 1): E_1[i, d+i] = 1 for i = 0, ..., d-1

## Algorithm: Fixed-Step EKF ODE Filter

### Initialization

    x_0 = [y_0; f(y_0); 0; ...; 0]     (known initial value and derivative, then zeros)
    P_0 = diag(eps, ..., eps, kappa, ..., kappa)
          where eps = 1e-10 for the 2d known components (y and y'),
          and kappa = 1.0 for the remaining d*(q-1) unknown higher derivatives
    sigma^2_0 = 1.0

### For each step k = 0, 1, ..., floor((t_1 - t_0) / h) - 1:

**Predict:**

    x_hat = A_full * x_k
    P_hat = A_full * P_k * A_full^T + sigma^2_k * Q_raw

where Q_raw = Q(h) (kron) I_d (the process noise with unit diffusion).

**Compute innovation (TS1 linearization):**

    y_hat = E_0 * x_hat                    (predicted state value)
    y'_hat = E_1 * x_hat                   (predicted first derivative)
    nu = f(y_hat) - y'_hat                 (innovation: how much the ODE constraint is violated)
    H = E_1 - J_f(y_hat) * E_0            (measurement Jacobian, d x N)

where J_f is the d x d Jacobian matrix of the vector field f.

**Update:**

    S = H * P_hat * H^T                    (innovation covariance, d x d)
    K = P_hat * H^T * S^{-1}              (Kalman gain, N x d)
    x_{k+1} = x_hat + K * nu
    P_{k+1} = (I_N - K * H) * P_hat       (recommend Joseph form for numerical stability)

For the Joseph form: P_{k+1} = (I_N - K*H) * P_hat * (I_N - K*H)^T
Symmetrize after each update: P = 0.5 * (P + P^T)

**Dynamic output scale (MLE):**

    c_k = nu^T * S^{-1} * nu               (normalized innovation squared, scalar)
    sigma^2_{k+1} = [k * sigma^2_k + c_k / d] / (k + 1)

This online update estimates the diffusion parameter that maximizes the
marginal likelihood. For a well-calibrated solver, c_k follows a chi-squared
distribution with d degrees of freedom, so E[c_k] = d.

## Calibration Diagnostics

The chi-squared calibration statistic is the mean of all normalized innovations:

    chi_sq_mean = mean(c_0, c_1, ..., c_{N_steps - 1})

For a well-calibrated solver, chi_sq_mean should be approximately d (the
dimension of the measurement space).

## Required Outputs

Write results to `/app/results/`:

1. `terminal_values.json`: `{"y1": <float>, "y2": <float>}`
   The posterior mean at the terminal time t_1 (first d components of x_final).

2. `calibration.json`: `{"chi_sq_mean": <float>, "output_scale": <float>}`
   Mean chi-squared statistic and final output scale sigma^2.

3. `iwp_check.json`: `{"A_01": <float>, "A_02": <float>, "A_03": <float>, "Q_00": <float>, "Q_33": <float>}`
   Specific entries of A(h) and Q(h) for the h and q values from config.json (0-indexed).
