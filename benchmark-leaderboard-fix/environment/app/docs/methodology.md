# Evaluation Methodology Notes

## Overview

This document describes candidate statistical approaches for evaluating
model performance on a continuously-refreshed code repair benchmark.
The pipeline must compute several metrics; for each, multiple candidate
implementations exist in `/app/candidates/`. This document provides
context for choosing the correct approach for standard benchmark reporting.

## 1. pass@k Estimation

The pass@k metric estimates the probability that at least one of k
samples drawn from a model's n completed runs solves a given task,
where c of those n runs were successful.

### Candidate A (`candidates/pass_at_k/variant_a.py`): Bernoulli Power Rule

Treats each of k draws as an independent Bernoulli trial with success
probability p = c/n, then computes pass@k = 1 - (1-p)^k.

**Properties**: Simple closed-form. However, this treats k as new
independent draws from an infinite population, which is incorrect
when we are sampling k runs without replacement from a finite pool
of n observed runs. Produces a biased estimate. For example, when
n = k = 5 and c = 1, the Bernoulli formula gives ~0.672 rather
than the correct value of 1.0 (since any 5-of-5 subset must include
the one success).

### Candidate B (`candidates/pass_at_k/variant_b.py`): Combinatorial (Hypergeometric)

Uses the exact combinatorial formula derived from the hypergeometric
distribution: pass@k = 1 - C(n-c, k) / C(n, k).

**Properties**: Unbiased estimator. Correct when n runs have already
been executed and we are estimating the probability that at least 1
of a k-sized subset succeeds. Equivalent to the standard formula
from Chen et al. (2021) used in HumanEval and SWE-bench reporting.
When n = k, any c > 0 yields pass@k = 1.0 (guaranteed to include
a success in the complete sample).

### Candidate C (`candidates/pass_at_k/variant_c.py`): Bayesian Beta Posterior

Models the success probability with a Beta(c+1, n-c+1) posterior
(uniform prior) and computes the expected probability that at least
one of k draws succeeds under the posterior.

**Properties**: Incorporates prior uncertainty. Produces shrunk
estimates that differ from the frequentist unbiased estimator,
especially for small n. The regularization toward the prior mean
means this metric is not directly comparable to the standard
pass@k values reported by other benchmarks.

---

## 2. Standard Error of the Mean (SEM)

SEM quantifies the uncertainty in the estimated resolved rate across
all model runs. Since each run produces a binary outcome (resolved or
not), the data follows a Bernoulli distribution.

### Candidate A (`candidates/sem/variant_a.py`): Population Formula

SEM = sqrt(p * (1-p) / n)

**Properties**: Assumes the observed sample IS the full population.
Uses n in the denominator. Underestimates the true variability when
the n observed runs are a finite sample from a larger hypothetical
population of possible evaluation runs.

### Candidate B (`candidates/sem/variant_b.py`): Bessel-Corrected Sample Formula

SEM = sqrt(p * (1-p) / (n-1))

**Properties**: Applies Bessel's correction (dividing by n-1 instead
of n) to provide an unbiased estimate of the population variance from
a finite sample. Yields a larger, more conservative SEM. Standard
practice in benchmark reporting where the runs represent a sample
from a theoretically unbounded number of possible evaluations.

### Candidate C (`candidates/sem/variant_c.py`): Cluster-Robust Standard Error

Groups runs by task and applies a design-effect correction to account
for within-task correlation (e.g., due to shared test infrastructure).

**Properties**: Appropriate when runs within the same task exhibit
non-negligible intra-cluster correlation. However, this changes
what SEM measures — it becomes the SE of the task-mean rather than
the run-level resolved rate. The ICC-based correction factor
introduces model assumptions (assumed ICC ~ 0.05) that alter the
metric's value even when no actual clustering effect exists.

---

## 3. Cost Per Problem

Computes the average dollar cost per problem based on per-run token
usage and the model's pricing tiers.

### Candidate A (`candidates/cost/variant_a.py`): Simple Token Cost

Computes cost using the full input token count at the standard input
rate, ignoring any distinction between cached and uncached tokens.

**Properties**: Overestimates actual cost when a significant fraction
of input tokens are served from prompt cache at a reduced rate.
Does not reflect real-world API billing.

### Candidate B (`candidates/cost/variant_b.py`): Tiered Token Cost

Splits input tokens into uncached (input - cached) and cached portions,
applying the appropriate rate to each tier:
cost = (uncached * input_rate + cached * cached_rate + output * output_rate) / 1M

**Properties**: Accurately models production API billing where cached
prompt tokens are charged at a reduced rate. Matches the cost model
used by major API providers. Each run's cost is computed independently
and then averaged.

### Candidate C (`candidates/cost/variant_c.py`): Cost Per Resolution

Computes total cost across all runs but divides by the number of
successful resolutions rather than total attempts, yielding the
effective cost to produce one successful solve.

**Properties**: Answers "how much does a successful resolution cost?"
rather than "how much does an attempt cost?". For models with low
resolve rates, this inflates the metric dramatically. Not suitable
as a per-problem cost metric since it conflates cost efficiency with
task difficulty and model capability.

---

## 4. Contamination Detection

A task-model pair is considered potentially contaminated if the task
existed in public repositories before the model's training data cutoff,
meaning the model could have seen the task's code during training.

**Standard definition**: A task is contaminated for a model if the
task's creation date is **strictly before** the model's release date.
Same-day creation is not considered contaminated (the task appeared
too late to enter training pipelines on that day).
