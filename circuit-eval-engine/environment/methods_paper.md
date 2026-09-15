# MIB Circuit Evaluation Methodology

## Overview

The Mechanistic Interpretability Benchmark (MIB) evaluates how faithfully discovered sub-circuits reproduce the behavior of full language models under interchange interventions. This document describes the evaluation protocol used to assess circuit discovery methods.

## Circuit Architecture

The model is represented as a directed graph where nodes are model components (embedding layer, attention heads, MLPs, output) and edges represent information flow paths. Each edge has:
- An **importance score** assigned by a circuit discovery method (may be positive or negative)
- A **type** determined by the destination component (`attn`, `mlp`, or `output`)
- A **weight** representing the parameter dimensionality (d_head for attention, d_mlp for MLP, 1 for output edges)

## Edge Selection Protocol

At each sparsity level, edges are selected based on the magnitude of their importance scores. In circuit analysis, both strongly positive and strongly negative attribution scores indicate functional significance — the sign reflects excitatory vs. inhibitory contributions, while the magnitude reflects importance. Therefore, edges are ranked by the absolute value of their importance score in descending order. When multiple edges share the same absolute score, ties are broken lexicographically by edge name (ascending order).

The number of edges to include at sparsity fraction p over N total edges uses the standard floor convention:

    k = floor(p * N)

When k = 0, no edges are active and the circuit produces the corrupted-baseline output.

## Sparsity Schedule

Evaluation is performed at 10 sparsity fractions:

    P = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0]

## Faithfulness

At each sparsity level, the selected edges form an active sub-circuit. All other edges are ablated via interchange intervention. The simulator computes a raw score for the active circuit.

Faithfulness normalizes this raw score relative to two anchors:
- **Corrupted score**: output when no edges are active (full ablation)
- **Baseline score**: output of the unmodified model (all edges active)

The normalized faithfulness measures recovery from the corrupted baseline toward clean-model behavior: a score of 0 means the circuit performs identically to the fully-ablated model, and 1 means it fully recovers clean-model performance. Values slightly above 1 can occur due to noise in the intervention process.

When k = 0, faithfulness is defined as 0.

## Aggregate Metrics

**CPR (Circuit Performance Recovery):** The trapezoidal integral of the faithfulness curve f(p) over the sparsity fractions. Higher CPR indicates better overall circuit quality.

**CMD (Circuit Minimal Distance):** The trapezoidal integral of the absolute deviation curve |1 - f(p)| over the sparsity fractions. Lower CMD indicates tighter convergence to ideal circuit behavior.

**Log-scale variants (CPR_log, CMD_log):** Same integrands as CPR and CMD, but the x-axis uses the natural logarithm of the sparsity fractions. This gives proportionally more weight to circuit behavior at very low sparsity levels, where the most informative edges should already contribute meaningful performance recovery.

## AUROC

AUROC evaluates how well the importance scores discriminate ground-truth circuit edges from non-circuit edges, treating circuit membership as the positive class. Edges are ranked by absolute importance score (descending, with lexicographic tie-breaking), and the standard trapezoidal ROC area is computed by walking through edges and accumulating true/false positive rates.

## Weighted Edge Count

At each sparsity level, the weighted edge count (WEC) is the sum of parameter weights for all active edges. This metric quantifies the computational cost of the sub-circuit.

## Method Ranking

Methods are ranked by their average metric value across all tasks:
- **CPR ranking:** Descending order (higher average CPR = better method)
- **CMD ranking:** Ascending order (lower average CMD = better method)
