#!/usr/bin/env python3
"""Score matrix to evaluation format converter.

Converts raw model prediction scores and binary relevance matrices
into the ranked-list JSON format consumed by eval_tool.py.

Usage: python3 score_converter.py <scores_dir> <output_dir>

Input files in <scores_dir>:
  - scores.json: 2D array of prediction scores (n_users x n_items)
  - relevance.json: 2D binary relevance matrix (n_users x n_items)
  - eval_config.yaml: evaluation configuration (YAML format)

Output files in <output_dir>:
  - ranked_lists.json
  - ground_truth.json
  - config.json
"""


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
        sorted_indices = np.argsort(scores[i])
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

    # Write config as JSON for eval_tool.py
    topk = config["topk"]
    out_config = {
        "topk": topk,
        "metrics": config.get("metrics", []),
        "num_items": n_items
    }

    with open(os.path.join(output_dir, "config.json"), "w") as f:
        json.dump(out_config, f)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <scores_dir> <output_dir>", file=sys.stderr)
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
