# Neural IR Analysis Framework

A framework for analyzing transformer-based retrieval models through activation patching
and differentiable ranking loss evaluation.

## Overview

This framework combines two key areas of neural information retrieval research:

1. **Activation Patching Analysis** — Measures how individual transformer components
   (residual stream blocks, attention heads) causally contribute to ranking behavior
   by replacing specific internal activations during a corrupted forward pass with
   values from a clean forward pass.

2. **Differentiable Ranking Losses** — A suite of loss functions commonly used in
   neural ranker training, implemented as PyTorch modules with a shared registry
   and base class.

3. **Standard Evaluation Metrics** — NDCG@k, MAP@k, and MRR for assessing ranking
   quality against ground-truth relevance labels.

## Project Structure

    /app/
    ├── analyze.py              # Main analysis pipeline
    ├── README.md               # This file
    ├── data/
    │   ├── model_config.json   # Model architecture and baseline scores
    │   ├── patching_data.json  # Pre-computed activation patching scores
    │   ├── ranking_data.json   # Query-document ranking examples (for loss eval)
    │   └── eval_data.json      # Query-document ranking examples (for metric eval)
    ├── framework/
    │   ├── __init__.py
    │   ├── base.py             # BaseLoss class, registry, reduction utilities
    │   ├── losses.py           # Ranking loss function implementations
    │   ├── patching.py         # Activation patching metric functions
    │   └── metrics.py          # Standard IR evaluation metrics
    └── output/
        └── report.json         # Generated analysis report

## Data Files

### model_config.json
- `n_layers`, `n_heads`, `d_model`, `seq_len`: Model architecture dimensions
- `clean_score`: Ranking score from an unperturbed (clean) forward pass
- `corrupted_score`: Ranking score from a fully corrupted forward pass

### patching_data.json
Pre-computed scores from activation patching experiments:
- `patching_block_scores`: 3D array, shape (3, n_layers, seq_len) — scores after
  patching each residual stream component type at each (layer, position).
  Component indices: 0=resid_pre, 1=attn_out, 2=mlp_out
- `patching_head_scores`: 2D array, shape (n_layers, n_heads) — scores after
  patching each attention head's output

### ranking_data.json
Array of objects for loss function evaluation, each with:
- `query_id`: Query identifier
- `predictions`: Model-predicted relevance scores (floats)
- `labels`: Ground-truth relevance grades (integers)

### eval_data.json
Array of objects for standard metric evaluation (same schema as ranking_data.json),
with queries where the model's ranking may not be perfect.

## Activation Patching Metric

The causal effect of patching a component is quantified using:

    effect = (patched_score - clean_score) / (corrupted_score - clean_score)

A value near 0 indicates the component is causally critical (patching it fully
restores clean behavior). A value near 1 indicates the component has minimal causal
importance for the observed ranking change.

## Loss Functions

The framework includes seven registered ranking losses: ApproxNDCG, ApproxMRR,
ListNet, RankNet, KL-Divergence, MarginMSE, and Contrastive. Each inherits from
`BaseLoss` and is registered via `@register_loss(key)` from `framework.base`.

## Evaluation Metrics (framework/metrics.py)

Standard IR evaluation metrics computed from predicted scores and relevance labels:

### NDCG@k (Normalized Discounted Cumulative Gain)
Sort documents by predicted scores (descending). Compute:
- DCG@k = sum_{i=1}^{k} (2^{rel_i} - 1) / log2(i + 1)
- IDCG@k = DCG@k for the ideal ranking (labels sorted descending)
- NDCG@k = DCG@k / IDCG@k (0 if IDCG is 0)

### AP@k (Average Precision at k)
Sort by predicted scores (descending). At each rank i <= k where the document is
relevant (label > 0), accumulate precision@i. Normalize by min(R, k) where R is
the total number of relevant documents in the full list. Returns 0 if no relevant
documents exist.

### MRR (Mean Reciprocal Rank)
Sort by predicted scores (descending). Return 1/rank where rank is the position
of the first relevant document (label > 0). Returns 0 if no relevant documents.

### evaluate_queries
Compute mean NDCG@k, MAP@k, and MRR across all queries in the eval dataset.
Returns a dict with keys: "ndcg", "map", "mrr".

## Expected Report Schema

Running `python3 /app/analyze.py` should produce `/app/output/report.json` with
the following structure:

    {
      "patching_analysis": {
        "block": {
          "top_5_critical": [[comp_idx, layer, pos], ...],
          "component_importance": {
            "resid_pre": <mean |effect| for component type 0>,
            "attn_out": <mean |effect| for component type 1>,
            "mlp_out": <mean |effect| for component type 2>
          },
          "most_critical_layer": <layer with lowest mean |effect|>,
          "most_critical_position": <position with lowest mean |effect|>
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

- "top_5_critical" entries are sorted by ascending absolute effect value (most
  critical first).
- "most_critical_layer" and "most_critical_position" are determined by the lowest
  mean absolute effect value across all block components.
- Loss values are computed with default parameters (temperature=1.0, mean reduction).
- Evaluation metrics are computed on eval_data.json with k=3.
