# Statistical Methodology Specification

This document specifies the statistical methods required for the perturbation robustness analysis report.

## Effect Sizes

Compute paired Hedges' g for each (model, perturbation) pair:

- For each task, obtain the success rate under the default baseline condition and the perturbed condition
- d_z = mean(baseline_rates - perturbed_rates) / std(baseline_rates - perturbed_rates, ddof=1)
- Apply small-sample correction: J = 1 - 3 / (4*(n-1) - 1), where n is the number of tasks
- Hedges' g = J * d_z
- If standard deviation is effectively zero, report g = 0

## Confidence Intervals

BCa (bias-corrected and accelerated) bootstrap 95% confidence intervals for each effect size:

- Number of resamples: 10,000
- Random seed: 42
- Bias-correction constant z0: normal quantile of the proportion of bootstrap replicates below the observed statistic
- Acceleration constant a: computed via jackknife leave-one-out estimates
- Adjust the nominal percentile endpoints using z0 and a before extracting CI bounds from the bootstrap distribution

## Sim-to-Real Correlation

Spearman rank correlation between simulation baseline success rates and real-world trial success rates across all valid (model, task) pairs.

95% confidence interval via Fisher z-transform:

- z = arctanh(rho), SE = 1/sqrt(n-3)
- Bounds = tanh(z +/- 1.96 * SE)

## Composite Robustness Index (CRI)

Per-model metric computed from relative performance drops across all (task, perturbation) combinations:

- relative_drop(task, pert) = (baseline_rate - perturbed_rate) / baseline_rate; use 0 if baseline_rate is 0
- mean_drop = mean of all relative drops
- CVaR_10 = mean of the largest (worst) 10% of relative drops (use ceiling for count)
- sensitivity_CV = std(per_perturbation_mean_drops, ddof=1) / |mean(per_perturbation_mean_drops)|

CRI = 0.5 * (1 - mean_drop) + 0.3 * (1 - CVaR_10) + 0.2 * (1 - sensitivity_CV)
