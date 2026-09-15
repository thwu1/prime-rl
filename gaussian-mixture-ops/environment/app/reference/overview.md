# Gaussian Mixture Operations — Overview

This library implements operations on isotropic Gaussian Mixtures (GMs)
for the GMFlow generative framework (arXiv 2504.05304).

## Tensor Convention

A GM with K components in D dimensions:
- `means` (bs, K, D) — component centres
- `logstds` (bs, 1, 1) — shared log standard deviation (one scalar, isotropic)
- `logweights` (bs, K, 1) — unnormalized log mixing weights

Weights: `softmax(logweights)`.
Component variance: `exp(2 * logstd)`.

## Operations

**gm_nll_loss** — Negative log-likelihood training loss. Drops the
Gaussian normalisation constant (irrelevant for optimisation). Uses
the log-sum-exp trick for numerical stability over components.

**gm_to_iso_gaussian** — Collapses a multi-component GM to a single
isotropic Gaussian via moment matching.

**gm_mul_iso_gaussian** — Bayesian posterior update: product of a
powered GM with a powered isotropic Gaussian, yielding a new GM.
Central to the SDE-based sampling procedure.

**gm_logprob** — Full normalised log-probability under the GM (with
the Gaussian normalisation constant). Returns both total and
per-component log-probabilities.

**gm_kl_div** — Monte Carlo KL(p||q) between two GMs.

**gm_logpdf_c** — Batch log-probability computation delegated to a
compiled C extension via ctypes. The C source is at `/app/gm_logpdf.c`
and must be compiled into `/app/libgm_logpdf.so`.

## Correct Helpers (do not modify)

**gm_to_sample** — Ancestral sampling from the mixture.
**gm_to_mean** — Weighted mean of component centres.
