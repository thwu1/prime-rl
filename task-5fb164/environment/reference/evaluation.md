# Scoring Framework Evaluation Methodology

Reference methodology for evaluating the information content of a battery of
correlated scoring methods and constructing a weighted consensus ranking.

## Dimensional Analysis

Principal component analysis of the inter-method Spearman rank correlation matrix
reveals how many independent quality dimensions the scoring methods collectively
measure.

### Retained Components (Kaiser Criterion)

Components whose eigenvalue meets or exceeds 1.0 (the average eigenvalue of a
correlation matrix) carry signal above the noise floor and should be retained.

### Method Importance Weights

A method's importance reflects how much of its variance is captured by the
retained components. For each retained component, a method's contribution is
its squared eigenvector loading on that component, scaled by the component's
eigenvalue. Sum these contributions across all retained components to get each
method's raw importance. Normalize the five importance values to sum to 1.0.

## Consensus Ranking Construction

To combine five correlated method-specific rankings into a single consensus:

1. For each method, convert raw scores to ordinal percentile ranks on [0, 1]
   (worst performer maps to 0.0, best to 1.0, linearly spaced for intermediate
   ranks)
2. Each forecaster's consensus score is the weighted sum of their percentile
   ranks across the five methods, using the importance weights derived above

## Stability Assessment

For each forecaster, compute the maximum rank position difference (spread)
across the five methods' descending rankings. Small spread indicates robust
standing regardless of scoring method; large spread indicates method-sensitive
evaluation.
