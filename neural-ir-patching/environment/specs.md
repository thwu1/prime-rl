# Neural IR Activation Patching Analysis Framework — Specifications

## Overview

This framework combines two areas from neural information retrieval research:

1. **Differentiable ranking loss functions** used for training neural rankers
2. **Activation patching metrics** from mechanistic interpretability applied to IR models
3. **Standard evaluation metrics** for ranking quality assessment

The framework operates on pre-computed activation patching data from a bi-encoder
(dot-product) retrieval model. Activation patching replaces specific internal model
activations during a corrupted forward pass with values from a clean forward pass,
measuring how each component causally contributes to ranking behavior.

## Data Files

- `/app/data/model_config.json` — Model architecture: n_layers, n_heads, d_model, seq_len, clean_score, corrupted_score
- `/app/data/patching_data.json` — Pre-computed scores after patching at each model component:
  - `patching_block_scores`: shape (3, n_layers, seq_len) — scores after patching residual stream components (resid_pre, attn_out, mlp_out) at each (layer, position)
  - `patching_head_scores`: shape (n_layers, n_heads) — scores after patching each attention head output across all positions
  - `patching_head_pos_scores`: shape (n_layers, n_heads, seq_len) — scores after patching each head at each position
- `/app/data/ranking_data.json` — Query-document ranking examples with predicted scores and relevance labels (for loss evaluation)
- `/app/data/eval_data.json` — Query-document ranking examples (for standard metric evaluation)

## Part 1: Patching Metrics (`/app/framework/patching.py`)

### linear_rank_function(patch_score, clean_score, corrupted_score)

Quantifies the causal effect of patching a model component on the ranking score.

    lrf(s_p, s_c, s_r) = (s_p - s_c) / (s_r - s_c)

where s_p is the score after patching, s_c is the clean (original) score, and s_r is
the corrupted (perturbed) score. Must support scalar, list, and nested list inputs.

**Interpretation**: A value near 0 means patching this component fully restored clean
behavior (the component is causally important). A value near 1 means patching had no
effect (the component is not important for the ranking change).

### compute_patching_effects(patching_scores, clean_score, corrupted_score)

Apply linear_rank_function element-wise to a nested list of patching scores.
Returns a nested list of the same shape containing effect values.

### identify_top_k_critical(effects, k=5)

Given a nested list of effect values (any dimensionality), return the k indices
(as tuples) with the smallest absolute effect value. These are the components
whose patching most strongly restored clean model behavior.

Sort by absolute effect value ascending. Return list of tuples.

## Part 2: Ranking Loss Functions (`/app/framework/losses.py`)

All loss functions must:
- Inherit from `BaseLoss` (in `framework.base`)
- Be registered with `@register_loss(key)` (from `framework.base`)
- Accept `pred` and `labels` as 2D PyTorch tensors of shape (batch, n_items)
- Return a scalar loss tensor after applying the configured reduction

### 1. ApproxNDCGLoss (key: "approx_ndcg")

Smooth NDCG approximation using sigmoid-based rank estimation.

Parameters: temperature (float, default 1.0), scale_gains (bool, default True)

Algorithm (per batch element):
1. Compute pairwise score differences and approximate ranks via a difference
   matrix. Concretely in PyTorch: form `score_diff = pred.unsqueeze(1) - pred.unsqueeze(2)`
   which gives `score_diff[i, j] = pred[j] - pred[i]`, apply sigmoid and mask
   the diagonal, then sum along the last axis and add 1 to get approximate ranks.
   Low ranks (near 1) correspond to high-scoring items.
2. Compute DCG using approximate ranks and relevance labels y (clamped >= 0):
     DCG = sum_i (2^y_i - 1) / log2(1 + approx_rank_i)
   If scale_gains is False, use y_i directly instead of 2^y_i - 1.
3. Compute ideal DCG (iDCG) using labels sorted descending at integer ranks 1..n.
4. NDCG = DCG / max(iDCG, 1e-12)
5. Loss = 1 - NDCG

### 2. ApproxMRRLoss (key: "approx_mrr")

Smooth MRR approximation using the same rank estimation as ApproxNDCG.

Parameters: temperature (float, default 1.0)

Algorithm (per batch element):
1. Compute approximate ranks as in ApproxNDCG.
2. Clamp labels to max value of 1 (binary relevance).
3. MRR = max_i(label_i / approx_rank_i)
4. Loss = 1 - MRR

### 3. ListNetLoss (key: "listnet")

Cross-entropy between label distribution and predicted score distribution.

Parameters: temperature (float, default 1.0), epsilon (float, default 1e-8)

Algorithm (per batch element):
1. If ANY label value is outside [0, 1], convert labels to probabilities:
   label_probs = softmax(labels / temperature)
2. Compute predicted log-probabilities:
   pred_log_probs = log_softmax(pred + epsilon / temperature)
3. Loss = -sum(label_probs * pred_log_probs)

### 4. RankNetLoss (key: "ranknet")

Pairwise preference learning via binary cross-entropy on score differences.

Parameters: temperature (float, default 1.0), reduction (str, default "mean")

Algorithm:
1. Generate upper-triangular pair indices (i, j) where i < j using torch.triu_indices.
2. Compute predicted differences: d_ij = pred[:, i] - pred[:, j]
3. Compute label differences and targets: target_ij = (labels[:, i] - labels[:, j] > 0).float()
4. Loss = BCEWithLogitsLoss(d_ij, target_ij)

Note: Use PyTorch's BCEWithLogitsLoss for numerical stability. The BCE operates
on the full flattened tensor with the specified reduction (typically "mean").

### 5. KLDivergenceLoss (key: "kl_div")

KL divergence between temperature-scaled softmax distributions.

Parameters: temperature (float, default 1.0), reduction (str, default "batchmean")

Algorithm:
  Loss = KLDivLoss(log_softmax(pred / T), softmax(labels / T))

Use PyTorch's KLDivLoss. The input must be log-probabilities and target must be probabilities.

### 6. MarginMSELoss (key: "margin_mse")

MSE on score residuals between positive (first) and negative (remaining) items.

Algorithm:
1. Predicted residuals: r_pred = pred[:, 0:1] - pred[:, 1:]
2. Label residuals: r_label = labels[:, 0:1] - labels[:, 1:]
3. Loss = MSE(r_pred, r_label) using PyTorch's mse_loss with configured reduction.

### 7. ContrastiveLoss (key: "contrastive")

Negative log-likelihood with temperature-scaled log-softmax.

Parameters: temperature (float, default 1.0)

Algorithm:
1. Compute log-softmax scores: log_probs = log_softmax(pred / temperature)
2. Target indices = argmax(labels, dim=1)
3. Loss = NLLLoss(log_probs, targets) with configured reduction.

## Part 3: Evaluation Metrics (`/app/framework/metrics.py`)

Standard IR evaluation metrics. The `RankingMetrics` class provides static methods
for computing metrics from prediction scores and relevance labels.

### ndcg_at_k(predictions, labels, k)

Compute NDCG (Normalized Discounted Cumulative Gain) at rank cutoff k.

Algorithm:
1. Sort document indices by predicted scores in descending order.
2. Using the sorted labels, compute DCG@k:
     DCG@k = sum_{i=1}^{min(k,n)} (2^{rel_i} - 1) / log2(i + 1)
   where rel_i is the relevance label of the document at rank i.
3. Compute IDCG@k: sort labels descending, compute DCG@k on the ideal ordering.
4. NDCG@k = DCG@k / IDCG@k. Return 0.0 if IDCG@k is 0.

Parameters: predictions (list of floats), labels (list of ints), k (int)
Returns: float in [0, 1]

### average_precision_at_k(predictions, labels, k)

Compute Average Precision at rank cutoff k.

Algorithm:
1. Sort document indices by predicted scores descending.
2. Let R = total number of relevant documents (label > 0) in the full list.
3. If R == 0, return 0.0.
4. Traverse ranks i = 1..min(k, n). Track count of relevant docs seen so far.
   When a relevant doc appears at rank i, accumulate precision@i = (relevant_so_far / i).
5. AP@k = sum_of_precisions / min(R, k)

Parameters: predictions (list), labels (list), k (int)
Returns: float in [0, 1]

### reciprocal_rank(predictions, labels)

Compute Reciprocal Rank.

Algorithm:
1. Sort document indices by predicted scores descending.
2. Find the rank of the first document with label > 0.
3. Return 1 / rank. If no relevant documents, return 0.0.

Parameters: predictions (list), labels (list)
Returns: float in [0, 1]

### evaluate_queries(ranking_data, k=5)

Compute mean metrics across all queries.

Algorithm:
1. For each query dict in ranking_data (has 'predictions' and 'labels'):
   - Compute ndcg_at_k(predictions, labels, k)
   - Compute average_precision_at_k(predictions, labels, k)
   - Compute reciprocal_rank(predictions, labels)
2. Return dict: {"ndcg": mean_ndcg, "map": mean_map, "mrr": mean_mrr}

## Part 4: Analysis Pipeline (`/app/analyze.py`)

Create a script that:
1. Loads all data from `/app/data/`
2. Computes patching effects using linear_rank_function on all three patching score matrices
3. Identifies top-5 most critical components for block patching and head patching
4. Evaluates ApproxNDCG, ApproxMRR, and ListNet losses on the ranking data
5. Evaluates NDCG@3, MAP@3, and MRR on the eval data using RankingMetrics
6. Writes results to `/app/output/report.json`

### Report Format (`/app/output/report.json`)

```json
{
  "patching_analysis": {
    "block": {
      "top_5_critical": [[comp_idx, layer, pos], ...],
      "component_importance": {
        "resid_pre": <mean |effect| for component 0>,
        "attn_out": <mean |effect| for component 1>,
        "mlp_out": <mean |effect| for component 2>
      },
      "most_critical_layer": <layer with lowest mean |effect| across all components and positions>,
      "most_critical_position": <position with lowest mean |effect| across all components and layers>
    },
    "head": {
      "top_5_critical": [[layer, head], ...],
      "mean_abs_effect": <mean |effect| across all heads>
    }
  },
  "loss_evaluation": {
    "approx_ndcg": <float>,
    "approx_mrr": <float>,
    "listnet": <float>
  },
  "evaluation_metrics": {
    "ndcg": <mean NDCG@3 across eval queries>,
    "map": <mean MAP@3 across eval queries>,
    "mrr": <mean MRR across eval queries>
  }
}
```

- "top_5_critical" entries are sorted by ascending absolute effect value (most critical first).
- "most_critical_layer" and "most_critical_position" are determined by the lowest mean absolute effect value across all block components.
- Loss values are computed with default parameters (temperature=1.0) and mean reduction.
- Evaluation metrics are computed on eval_data.json with k=3.
