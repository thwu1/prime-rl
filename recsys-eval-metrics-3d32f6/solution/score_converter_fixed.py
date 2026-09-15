#!/usr/bin/env python3
"""Fixed score matrix to evaluation format converter."""


import json
import sys
import os
import numpy as np
import yaml


def convert(scores_dir, output_dir):
    with open(os.path.join(scores_dir, "scores.json")) as f:
        scores = np.array(json.load(f), dtype=np.float64)

    with open(os.path.join(scores_dir, "relevance.json")) as f:
        relevance = np.array(json.load(f), dtype=np.float64)

    with open(os.path.join(scores_dir, "eval_config.yaml")) as f:
        config = yaml.safe_load(f)

    n_users, n_items = scores.shape

    # Build ranked item lists from prediction scores
    ranked_users = []
    for i in range(n_users):
        # FIX 1: Use descending sort (negate scores for argsort)
        sorted_indices = np.argsort(-scores[i])
        # Convert 0-based array indices to 1-based item IDs
        ranked_items = (sorted_indices + 1).tolist()
        ranked_users.append({
            "user_id": i,
            "ranked_items": ranked_items
        })

    # Build ground truth from relevance matrix
    gt_users = []
    for i in range(n_users):
        rel_indices = np.where(relevance[i] > 0)[0]
        relevant_items = (rel_indices + 1).tolist()
        gt_users.append({
            "user_id": i,
            "relevant_items": relevant_items
        })

    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, "ranked_lists.json"), "w") as f:
        json.dump({"users": ranked_users}, f)

    with open(os.path.join(output_dir, "ground_truth.json"), "w") as f:
        json.dump({"users": gt_users}, f)

    # FIX 2: Wrap scalar topk in list
    topk = config["topk"]
    if isinstance(topk, int):
        topk = [topk]

    # FIX 3: Use num_items from config, not score matrix width
    out_config = {
        "topk": topk,
        "metrics": config.get("metrics", []),
        "num_items": config.get("num_items", n_items)
    }

    with open(os.path.join(output_dir, "config.json"), "w") as f:
        json.dump(out_config, f)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <scores_dir> <output_dir>", file=sys.stderr)
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
