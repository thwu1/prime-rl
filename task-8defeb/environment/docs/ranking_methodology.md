# Ranking Methodology for Biomedical Image Analysis Challenges

*Adapted from Maier-Hein et al., "Why rankings of biomedical image analysis competitions should be interpreted with care," Nature Communications, 2018; and Wiesenfarth et al., "Methods and open-source toolkit for analyzing and visualizing challenge results," Scientific Reports, 2021.*

## Rank-then-Aggregate Bootstrap

Challenge rankings should account for the uncertainty inherent in finite test sets. The recommended approach:

1. **Bootstrap resampling**: Draw B = 1000 bootstrap samples from the test cases using a fixed random seed of 42 (via `numpy.random.RandomState(42)`). When test cases fall into distinct clinical categories of varying difficulty, sampling should be **stratified** — draw independently within each stratum, preserving stratum sizes, to ensure category proportions are maintained in every resample. Iterate over strata in lexicographic order of category names.

2. **Per-metric ranking**: Within each bootstrap iteration, compute each team's mean score over the sampled cases for each evaluation metric. Rank teams per metric where rank 1 is best. For metrics where higher values indicate better performance (e.g., Dice, detection F1), rank by descending mean score. For metrics where lower values indicate better performance (e.g., volume difference, count difference), rank by ascending mean score. Ties receive the average of the ranks they would span (`scipy.stats.rankdata` with `method="average"`).

3. **Combined rank**: Each team's combined rank in a given iteration is the arithmetic mean of its per-metric ranks across all four metrics.

4. **Aggregation**: The final team ordering is determined by each team's mean combined rank across all B iterations (ascending — lowest mean rank = best team). Additionally, report the fraction of bootstrap iterations in which each team achieved the best (lowest) combined rank.

## Confidence Intervals

Report the 2.5th and 97.5th percentiles of each team's combined rank distribution across bootstrap iterations as a 95% bootstrap confidence interval, using `numpy.percentile`.

## Ranking Stability via Leave-One-Out Analysis

To assess how robust the ranking is to individual test cases, perform a leave-one-out (LOO) analysis. For each test case in turn:

1. Exclude that case from the dataset
2. Recompute the complete stratified bootstrap ranking on the remaining cases (using the same B = 1000 iterations, same seed 42, same stratification logic — strata that become empty after exclusion are simply omitted)
3. Record the resulting team ordering

The **ranking displacement** for a given excluded case is the sum of absolute changes in rank position across all teams compared to the full-dataset ranking. The **most influential case** is the one whose exclusion produces the largest total ranking displacement. In case of ties, select the case that comes first in lexicographic order.

## Notes on Statistical Testing

When performing multiple pairwise statistical comparisons (e.g., between consecutively ranked teams), raw p-values must be corrected for multiple testing to control the family-wise error rate. The Holm-Bonferroni step-down procedure is recommended:

1. Sort the m raw p-values in ascending order: p_(1) ≤ p_(2) ≤ ... ≤ p_(m)
2. Compute adjusted p-values: q_(k) = min((m - k + 1) · p_(k), 1.0)
3. Enforce monotonicity: q_(k) = max(q_(k), q_(k-1)) for k ≥ 2
4. Map adjusted values back to the original comparison ordering
