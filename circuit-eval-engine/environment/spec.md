
# MIB Circuit Evaluation Protocol Specification

## Overview

The Mechanistic Interpretability Benchmark (MIB) evaluates circuit discovery methods by measuring how faithfully a discovered sub-circuit reproduces the behavior of the full model. Three classes of metrics are used: **CPR** (Circuit Performance Recovery), **CMD** (Circuit Minimal Distance), and **AUROC** (Area Under the ROC Curve).

## Definitions

### Circuit Graph

A circuit graph consists of directed edges between model components. Each edge has:
- A **name** (string, formatted as `"src->dst"`)
- A **score** (float): the importance score assigned by a circuit discovery method
- A **type** (string): `"attn"`, `"mlp"`, or `"output"` — determined by the destination node
- A **weight** (int): the number of parameters this edge represents (`d_head` for attention edges, `d_mlp` for MLP edges, `1` for output edges)

### Edge Selection

At a given sparsity level (expressed as a fraction `p` of total edges), the top-k edges are selected:

```
k = floor(p * N)
```

where `N` is the total number of edges. Edges are ranked by **absolute value** of their importance score in **descending** order. Ties are broken **lexicographically** by edge name (ascending).

When `k = 0`, no edges are active and the circuit score equals the corrupted score.

### Sparsity Levels

Evaluation is performed at 10 fixed sparsity fractions:

```
P = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0]
```

### Faithfulness

At each sparsity level, the **raw score** is obtained by passing the set of active edge names to the simulator's `evaluate()` method. The **normalized faithfulness** is:

```
f(p) = (raw_score(p) - corrupted_score) / (baseline_score - corrupted_score)
```

where `baseline_score` and `corrupted_score` are task-specific constants from the simulator configuration. When `k = 0`, `f(p) = 0`.

### Weighted Edge Count

At each sparsity level, the **weighted edge count** is the sum of the `weight` values for all active edges:

```
WEC(p) = sum(edge.weight for edge in active_edges)
```

### CPR (Circuit Performance Recovery)

CPR is the area under the faithfulness curve, computed via trapezoidal integration over the sparsity fractions:

```
CPR = sum_{i=0}^{8} (P[i+1] - P[i]) * (f(P[i]) + f(P[i+1])) / 2
```

Higher CPR indicates better circuit performance recovery. The maximum possible CPR is 0.999 (the area of a rectangle of height 1 from 0.001 to 1.0).

### CMD (Circuit Minimal Distance)

CMD measures how far the faithfulness curve is from perfect recovery:

```
CMD = sum_{i=0}^{8} (P[i+1] - P[i]) * (|1 - f(P[i])| + |1 - f(P[i+1])|) / 2
```

Lower CMD indicates better circuit performance recovery.

### Log-Scale Variants

CPR and CMD have log-scale variants where the x-axis uses the natural logarithm of the sparsity fractions:

```
CPR_log = sum_{i=0}^{8} (ln(P[i+1]) - ln(P[i])) * (f(P[i]) + f(P[i+1])) / 2
CMD_log = sum_{i=0}^{8} (ln(P[i+1]) - ln(P[i])) * (|1 - f(P[i])| + |1 - f(P[i+1])|) / 2
```

Note that `ln(P[0]) = ln(0.001) ≈ -6.908`.

### AUROC (Area Under ROC Curve)

AUROC measures how well a method's importance scores discriminate between edges in the ground-truth circuit and edges not in it.

To compute AUROC:

1. Sort all edges by absolute importance score (descending), with ties broken lexicographically by edge name (ascending) — same ordering as for edge selection.
2. Initialize `TP = 0`, `FP = 0`. The ground truth has `n_pos` positive edges (in circuit) and `n_neg` negative edges (not in circuit).
3. Start the ROC curve at `(FPR=0, TPR=0)`.
4. Walk through edges in ranked order. For each edge:
   - If it is in the ground-truth circuit: `TP += 1`
   - Otherwise: `FP += 1`
   - Record the point `(FPR = FP/n_neg, TPR = TP/n_pos)`
5. Compute AUROC via trapezoidal integration over these points:
   ```
   AUROC = sum_{i=0}^{N-1} (FPR[i+1] - FPR[i]) * (TPR[i] + TPR[i+1]) / 2
   ```

AUROC = 1.0 indicates perfect separation; AUROC = 0.5 indicates random ranking.

## Method Ranking

Methods are ranked by **average** metric value across all tasks:
- `by_cpr`: sorted by average CPR in **descending** order (higher CPR = better)
- `by_cmd`: sorted by average CMD in **ascending** order (lower CMD = better)

## Output Format

The output must be a JSON object with this structure:

```json
{
  "methods": {
    "<method_name>": {
      "<task_name>": {
        "faithfulnesses": [f_1, f_2, ..., f_10],
        "weighted_edge_counts": [w_1, w_2, ..., w_10],
        "cpr": <float>,
        "cmd": <float>,
        "cpr_log": <float>,
        "cmd_log": <float>
      }
    }
  },
  "auroc": {
    "<method_name>": {
      "<task_name>": <float>
    }
  },
  "ranking": {
    "by_cpr": ["<best_method>", "<second_best>", "<worst>"],
    "by_cmd": ["<best_method>", "<second_best>", "<worst>"]
  }
}
```

Methods: `eap`, `eap_ig`, `act_patch`. Tasks: `ioi`, `mcqa`.
