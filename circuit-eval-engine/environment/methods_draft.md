# MIB Circuit Evaluation — Methods Draft (v0.3, incomplete)

## Overview

The MIB benchmark evaluates circuit discovery methods by measuring how faithfully discovered sub-circuits approximate full-model behavior under interchange interventions. Each discovery method assigns importance scores to edges in the model's computational graph; the evaluation measures whether selecting high-importance edges produces circuits that recover model behavior.

## Circuit Graph

Nodes represent model components (embedding layer, attention heads per layer, MLP blocks per layer, output layer). Edges represent information flow between components. Each edge has:
- An importance score (positive or negative — sign encodes excitatory vs. inhibitory contribution, not importance)
- A type based on destination component
- A parameter weight reflecting dimensionality

## Edge Selection Protocol

At each sparsity fraction p, a sub-circuit is formed by selecting the most important edges. The selection criterion should reflect that functionally significant edges may have either sign — an edge with importance score -2.5 contributes more to the circuit than one with score +0.3.

The number of edges k at fraction p over N total edges should be conservative: the active sub-circuit must not exceed the budget that fraction p implies.

> Note: verify whether the convention is truncation or rounding. Prior implementations have used both. The conservative choice ensures the circuit never exceeds its sparsity budget.

Ties are broken lexicographically by edge name (ascending).

## Sparsity Schedule

P = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0]

## Faithfulness

Faithfulness quantifies how well the active sub-circuit recovers clean-model behavior. It is normalized between two anchors:
- **Corrupted score**: model output when no circuit edges are active (complete ablation)
- **Baseline score**: output of the unmodified model (all edges active)

Properties:
- f = 0 when the circuit is empty (indistinguishable from fully-ablated model)
- f = 1 when the circuit fully recovers clean-model performance
- f > 1 is possible due to intervention noise
- f should increase monotonically (on average) as more edges are included

When k = 0, faithfulness is defined as 0.

## Aggregate Metrics

**CPR (Circuit Performance Recovery):** Trapezoidal integral of f(p) over the sparsity fractions. Higher is better.

**CMD (Circuit Minimal Distance):** Trapezoidal integral of |1 - f(p)| over the sparsity fractions. Lower is better.

**Log-scale variants (CPR_log, CMD_log):** Same integrands, but the integration variable is the natural logarithm of the sparsity fraction. This weights low-sparsity behavior more heavily, rewarding methods that identify important edges early.

## AUROC

Evaluates discriminative quality of importance scores: how well they separate ground-truth circuit edges from non-circuit edges. Uses the same ranking criterion as the edge selection protocol, with standard trapezoidal ROC area computation.

## Weighted Edge Count (WEC)

Sum of parameter weights for all active edges at each sparsity level. Quantifies the computational cost of the sub-circuit.

## Method Ranking

Methods are ranked by average metric value across all tasks:
- CPR ranking: descending (higher average = better)
- CMD ranking: ascending (lower average = better)
