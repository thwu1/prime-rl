# Sim-to-Real Transfer Evaluation Framework

## Context

In robotic manipulation research, simulation environments are used to evaluate learned control policies before expensive real-world testing. The central question is: how well do simulated success rates predict real-world performance? This analysis compares two simulation evaluation approaches against ground-truth real-world results across multiple manipulation tasks and policies.

## Simulation Approaches

### Visual Matching

Selects the single simulation environment variant that most closely matches the visual appearance of the real-world setting. This approach provides a direct one-to-one mapping of simulated success rates to real-world success rates.

### Variant Aggregation

Combines results from multiple simulation environment variants (differing in lighting, textures, backgrounds) into a single aggregated prediction per task-policy pair. Each variant is assigned a quality weight reflecting its fidelity. When an observation is missing for a particular variant, that variant is excluded from the aggregation and the remaining weights are renormalized before computing the weighted mean.

## Evaluation Metrics

### Ranking Consistency (MMRV)

MMRV (Mean Maximum Ranking Violation) quantifies the worst-case rank-order disagreement between simulation and reality. For each manipulation task, policies are ranked by success rate in descending order (rank 1 = highest success rate). Tied values receive the average of the rank positions they would span. The metric then examines all pairs of policies and identifies cases where simulation and reality disagree on the relative ordering. Among those disagreements, it measures the magnitude of the worst-case rank displacement. The per-task maximum violations are averaged across all tasks.

### Global Correlation

Linear association between simulated and real-world success rates is measured using the Pearson product-moment correlation coefficient (with two-tailed p-value) and Kendall's rank correlation with tie correction (tau-b variant). These are computed across all task-policy pairs, with observations ordered lexicographically by task name then policy name.

### Per-Task Correlation

Pearson correlation is also computed within each individual task across its policies (ordered alphabetically by policy name). If all simulation values for a task are identical (zero variance), the correlation is mathematically undefined and should be reported as null.

### Aggregate Per-Task Correlation

Direct arithmetic averaging of correlation coefficients is statistically inappropriate due to the bounded, nonlinear nature of the correlation scale. The standard approach applies a variance-stabilizing transformation to each valid (non-null) per-task correlation value, computes the arithmetic mean in the transformed space, then applies the inverse transformation to recover a mean correlation coefficient. Null (undefined) per-task correlations are excluded from this computation.

### Prediction Error

Normalized root mean square error (NRMSE) scales the RMSE by the observed range of real-world success rates (global max minus global min across all task-policy pairs). Systematic bias is the mean signed prediction error: simulation minus reality, averaged across all pairs.

### Uncertainty Quantification

A percentile-based bootstrap 95% confidence interval for the global Pearson correlation coefficient is computed via case resampling. A fixed random seed (stored in the database configuration) ensures reproducibility. Bootstrap iterations that produce undefined correlations (due to zero-variance resampled arrays) are discarded. The 2.5th and 97.5th percentiles of valid bootstrap correlation values define the confidence interval bounds.
