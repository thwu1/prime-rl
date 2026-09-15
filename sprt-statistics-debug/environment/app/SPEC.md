# SPRT Statistical Analysis — Mathematical Specification

This document specifies the correct mathematical formulas used by the
SPRT analysis engine. Use it as a reference when debugging the code
in `stats/`.

## 1. Score Mapping (results_to_pdf)

Given game results of length K (K=3 for trinomial L/D/W, K=5 for
pentanomial LL/LD/DD/WD/WW), construct a discrete probability
distribution:

- **Score values**: `s_i = i / (K - 1)` for `i = 0, 1, ..., K-1`
- For trinomial (K=3): scores are `[0, 1/2, 1]`
- For pentanomial (K=5): scores are `[0, 1/4, 1/2, 3/4, 1]`
- **Probabilities**: `p_i = results[i] / N` where `N = sum(results)`

The score range is always [0, 1]. The denominator is `K-1`, not `K`.

## 2. Logistic Elo Function

The logistic function maps Elo difference to expected score:

    L(x) = 1 / (1 + 10^(-x / 400))

Key properties:
- `L(0) = 0.5`
- `L(x) + L(-x) = 1` (symmetry)
- `L(400) = 10/11`

## 3. BayesElo Model

BayesElo parameterizes win/loss/draw probabilities using `elo` and
`drawelo`:

    P_win  = 1 / (1 + 10^((-elo + drawelo) / 400))
    P_loss = 1 / (1 + 10^(( elo + drawelo) / 400))
    P_draw = 1 - P_win - P_loss

**Note the denominator is 400**, consistent with the standard Elo
scale. The `drawelo` parameter controls the draw rate independently
of the win/loss ratio.

Inverse (proba_to_bayeselo):

    elo    = 200 * log10(P_win / P_loss * (1 - P_loss) / (1 - P_win))
    drawelo = 200 * log10((1 - P_loss) / P_loss * (1 - P_win) / P_win)

## 4. Maximum Likelihood Estimation (MLE)

Given an empirical distribution `{(a_i, p_i)}` and a target expected
value `s`, compute the MLE distribution `{(a_i, q_i)}` where:

    q_i = p_i / (1 + lambda * (a_i - s))

and `lambda` is found by solving the secular equation:

    sum_i  p_i * (a_i - s) / (1 + lambda * (a_i - s))  =  0

The shift is `(a_i - s)`, centering the values around the target `s`.

## 5. Log-Likelihood Ratio (LLR)

### Exact LLR (per game)

    LLR(s0, s1) = sum_i  p_i * log(q1_i / q0_i)

where `q0`, `q1` are the MLE distributions at scores `s0`, `s1`.

### Approximate LLR (LLR_alt2, per game)

    LLR ≈ (s1 - s0) * (2*mu - s0 - s1) / (2 * sigma^2)

where `mu` and `sigma^2` are the mean and **variance** (not standard
deviation) of the empirical distribution.

## 6. LLR Drift and Variance (Brownian Approximation)

When modeling the LLR process as Brownian motion with boundaries:

    drift:    mu_LLR    = (s - (s0 + s1) / 2) * (s1 - s0) / sigma^2
    variance: sigma^2_LLR = (s1 - s0)^2 / sigma^2

where:
- `s` is the true expected score (or the observed score if unknown)
- `sigma^2` is the **variance** of the PDF (not standard deviation)
- The denominator is `sigma^2`, not `sigma`

## 7. Brownian Motion Boundary Crossing

For a Brownian motion starting at position `x` in `(0, A)` with
absorbing boundaries at 0 and A:

### Pre-factor (exit probability through upper boundary)

Three cases based on `gamma = mu / sigma^2`:

1. `|gamma * A| < epsilon`:  `pre ≈ (A - x) / A`
2. `gamma * A > 30`:         `pre ≈ exp(-2 * gamma * x)`
3. Otherwise:                `pre = (1 - exp(2*gamma*(A - x))) / (1 - exp(2*gamma*A))`

In case 3, the numerator uses `(A - x)`, the distance from the
starting point to the **upper** boundary, not `x` (the distance to
the lower boundary).

Here `A = b - a` and `x = 0 - a` (starting position shifted into
[0, A] coordinates).

## 8. Normalized Elo and Pentanomial Model

For the normalized Elo model, the per-game standard deviation
`sigma_pg` is computed from the PDF variance:

- **Pentanomial** (game pairs, K=5): `sigma_pg = sqrt(2 * Var(pdf))`
- **Trinomial** (single games, K=3): `sigma_pg = sqrt(Var(pdf))`

The factor of **2** for pentanomial accounts for the fact that each
pentanomial entry represents a **pair** of games. The variance of the
pair-averaged distribution is half the per-game variance, so we
multiply by 2 before taking the square root.

## 9. SPRT Decision Boundaries

The SPRT boundaries are:

    a = log(beta / (1 - alpha))        (lower bound, reject H1)
    b = log((1 - beta) / alpha)        (upper bound, accept H1)

where `alpha` is the false positive rate and `beta` is the false
negative rate.

The test accepts H1 when `LLR >= b` and rejects when `LLR <= a`.
