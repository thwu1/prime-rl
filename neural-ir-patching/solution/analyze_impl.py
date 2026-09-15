
"""Analysis pipeline: loads data, computes patching effects, evaluates losses."""

import json
import os
import sys

sys.path.insert(0, "/app")

import torch
from framework.patching import (
    compute_patching_effects,
    identify_top_k_critical,
)
from framework.losses import ApproxNDCGLoss, ApproxMRRLoss, ListNetLoss
from framework.metrics import RankingMetrics


def load_json(path):
    with open(path) as f:
        return json.load(f)


def mean_abs(nested):
    """Compute mean of absolute values in a nested list."""
    flat = list(_flatten(nested))
    return sum(abs(v) for v in flat) / len(flat)


def _flatten(data):
    if isinstance(data, (list, tuple)):
        for item in data:
            yield from _flatten(item)
    else:
        yield data


def main():
    # Load data
    config = load_json("/app/data/model_config.json")
    patching = load_json("/app/data/patching_data.json")
    ranking = load_json("/app/data/ranking_data.json")
    eval_data = load_json("/app/data/eval_data.json")

    clean_score = config["clean_score"]
    corrupted_score = config["corrupted_score"]
    n_layers = config["n_layers"]
    n_heads = config["n_heads"]
    seq_len = config["seq_len"]

    # ---- Patching analysis ----

    block_scores = patching["patching_block_scores"]
    head_scores = patching["patching_head_scores"]

    block_effects = compute_patching_effects(block_scores, clean_score, corrupted_score)
    head_effects = compute_patching_effects(head_scores, clean_score, corrupted_score)

    # Top-5 critical block components
    top5_block = identify_top_k_critical(block_effects, k=5)
    top5_block = [list(t) for t in top5_block]

    # Top-5 critical heads
    top5_head = identify_top_k_critical(head_effects, k=5)
    top5_head = [list(t) for t in top5_head]

    # Component importance (mean |effect| per component type)
    comp_names = ["resid_pre", "attn_out", "mlp_out"]
    component_importance = {}
    for i, name in enumerate(comp_names):
        vals = [abs(block_effects[i][l][p]) for l in range(n_layers) for p in range(seq_len)]
        component_importance[name] = sum(vals) / len(vals)

    # Most critical layer
    layer_importance = []
    for l in range(n_layers):
        vals = [abs(block_effects[c][l][p]) for c in range(3) for p in range(seq_len)]
        layer_importance.append(sum(vals) / len(vals))
    most_critical_layer = layer_importance.index(min(layer_importance))

    # Most critical position
    pos_importance = []
    for p in range(seq_len):
        vals = [abs(block_effects[c][l][p]) for c in range(3) for l in range(n_layers)]
        pos_importance.append(sum(vals) / len(vals))
    most_critical_position = pos_importance.index(min(pos_importance))

    # Head mean absolute effect
    head_flat = [abs(head_effects[l][h]) for l in range(n_layers) for h in range(n_heads)]
    head_mean_abs = sum(head_flat) / len(head_flat)

    # ---- Loss evaluation ----

    preds = torch.tensor(
        [d["predictions"] for d in ranking], dtype=torch.float32
    )
    labels = torch.tensor(
        [[float(l) for l in d["labels"]] for d in ranking], dtype=torch.float32
    )

    with torch.no_grad():
        ndcg_loss = ApproxNDCGLoss(temperature=1.0, reduction="mean")
        mrr_loss = ApproxMRRLoss(temperature=1.0, reduction="mean")
        listnet_loss = ListNetLoss(temperature=1.0, reduction="mean")

        approx_ndcg_val = ndcg_loss(preds, labels).item()
        approx_mrr_val = mrr_loss(preds, labels).item()
        listnet_val = listnet_loss(preds, labels).item()

    # ---- Evaluation metrics ----

    eval_metrics = RankingMetrics.evaluate_queries(eval_data, k=3)

    # ---- Build report ----

    report = {
        "patching_analysis": {
            "block": {
                "top_5_critical": top5_block,
                "component_importance": component_importance,
                "most_critical_layer": most_critical_layer,
                "most_critical_position": most_critical_position,
            },
            "head": {
                "top_5_critical": top5_head,
                "mean_abs_effect": head_mean_abs,
            },
        },
        "loss_evaluation": {
            "approx_ndcg": approx_ndcg_val,
            "approx_mrr": approx_mrr_val,
            "listnet": listnet_val,
        },
        "evaluation_metrics": eval_metrics,
    }

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Report written to /app/output/report.json")


if __name__ == "__main__":
    main()
