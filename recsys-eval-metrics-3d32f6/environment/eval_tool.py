#!/usr/bin/env python3
"""Recommendation evaluation tool — designed to be compatible with RecBole framework metrics.

Usage: python3 eval_tool.py <input_dir> <output_file>

Reads ranked_lists.json, ground_truth.json, and config.json from <input_dir>.
Writes metric results as JSON to <output_file>.
"""


import json
import sys
import math
import os
from collections import Counter


def load_data(input_dir):
    with open(os.path.join(input_dir, "ranked_lists.json")) as f:
        ranked = json.load(f)
    with open(os.path.join(input_dir, "ground_truth.json")) as f:
        gt = json.load(f)
    with open(os.path.join(input_dir, "config.json")) as f:
        config = json.load(f)
    return ranked, gt, config


# ---------------------------------------------------------------------------
# Per-user ranking metrics
# ---------------------------------------------------------------------------

def compute_hit(pos_indicator):
    """1 if at least one relevant item in the top-K list, else 0."""
    return 1.0 if sum(pos_indicator) > 0 else 0.0


def compute_recall(pos_indicator, pos_len):
    """Fraction of relevant items found in top-K."""
    if pos_len == 0:
        return 0.0
    return sum(pos_indicator) / pos_len


def compute_precision(pos_indicator):
    """Fraction of top-K items that are relevant."""
    k = len(pos_indicator)
    if k == 0:
        return 0.0
    return sum(pos_indicator) / k


def compute_mrr(pos_indicator):
    """Mean reciprocal rank — reciprocal of the rank of relevant items."""
    rr_sum = 0.0
    count = 0
    for i, v in enumerate(pos_indicator):
        if v > 0:
            rr_sum += 1.0 / (i + 1)
            count += 1
    if count == 0:
        return 0.0
    return rr_sum / count


def compute_ndcg(pos_indicator, pos_len):
    """Normalized DCG with log2 discounting."""
    k = len(pos_indicator)
    if pos_len == 0 or k == 0:
        return 0.0
    dcg = sum(pos_indicator[i] / math.log2(i + 2) for i in range(k))
    idcg = sum(1.0 / math.log2(i + 2) for i in range(pos_len))
    if idcg == 0:
        return 0.0
    return dcg / idcg


def compute_map(pos_indicator, pos_len):
    """Mean average precision."""
    k = len(pos_indicator)
    if pos_len == 0 or k == 0:
        return 0.0
    cumsum = 0
    sum_prec = 0.0
    for i in range(k):
        cumsum += pos_indicator[i]
        if pos_indicator[i] > 0:
            sum_prec += cumsum / (i + 1)
    return sum_prec / k


# ---------------------------------------------------------------------------
# System-level diversity metrics
# ---------------------------------------------------------------------------

def compute_item_coverage(all_top_k, num_items):
    """Fraction of the catalog that appears in at least one user's top-K."""
    unique = set()
    for items in all_top_k:
        unique.update(items)
    return len(unique) / num_items


def compute_gini_index(all_top_k, num_items):
    """Gini coefficient of item recommendation frequency distribution."""
    flat = []
    for items in all_top_k:
        flat.extend(items)
    if not flat:
        return 0.0
    cnt = Counter(flat)
    sorted_counts = sorted(cnt.values())
    num_recommended = len(sorted_counts)
    total_recs = len(flat)
    gini = 0.0
    for i, c in enumerate(sorted_counts):
        gini += (2 * (i + 1) - num_recommended - 1) * c
    gini /= total_recs
    gini /= num_recommended
    return gini


def compute_shannon_entropy(all_top_k):
    """Shannon entropy of item frequency distribution (natural log)."""
    flat = []
    for items in all_top_k:
        flat.extend(items)
    if not flat:
        return 0.0
    cnt = Counter(flat)
    total_recs = len(flat)
    if len(cnt) == 0:
        return 0.0
    entropy = 0.0
    for c in cnt.values():
        p = c / total_recs
        entropy += -p * math.log(p)
    return entropy


# ---------------------------------------------------------------------------
# Main evaluation pipeline
# ---------------------------------------------------------------------------

def evaluate(input_dir, output_file):
    ranked, gt, config = load_data(input_dir)
    topk_values = config["topk"]
    metric_names = [m.lower() for m in config["metrics"]]
    num_items = config.get("num_items", 0)

    gt_map = {}
    for u in gt["users"]:
        gt_map[u["user_id"]] = set(u["relevant_items"])

    users_data = []
    for u in ranked["users"]:
        uid = u["user_id"]
        items = u["ranked_items"]
        relevant = gt_map.get(uid, set())
        users_data.append((uid, items, relevant))

    results = {}

    for k in topk_values:
        per_user = {m: [] for m in ["recall", "precision", "hit", "mrr", "ndcg", "map"]}
        all_top_k = []

        for uid, items, relevant in users_data:
            top_k = items[:k]
            all_top_k.append(top_k)
            pos_len = len(relevant)
            pi = [1.0 if item in relevant else 0.0 for item in top_k]

            per_user["recall"].append(compute_recall(pi, pos_len))
            per_user["precision"].append(compute_precision(pi))
            per_user["hit"].append(compute_hit(pi))
            per_user["mrr"].append(compute_mrr(pi))
            per_user["ndcg"].append(compute_ndcg(pi, pos_len))
            per_user["map"].append(compute_map(pi, pos_len))

        for m in ["recall", "precision", "hit", "mrr", "ndcg", "map"]:
            if m in metric_names and per_user[m]:
                results[f"{m}@{k}"] = round(sum(per_user[m]) / len(per_user[m]), 4)

        if "itemcoverage" in metric_names:
            results[f"itemcoverage@{k}"] = round(compute_item_coverage(all_top_k, num_items), 4)
        if "giniindex" in metric_names:
            results[f"giniindex@{k}"] = round(compute_gini_index(all_top_k, num_items), 4)
        if "shannonentropy" in metric_names:
            results[f"shannonentropy@{k}"] = round(compute_shannon_entropy(all_top_k), 4)

    out_dir = os.path.dirname(output_file)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input_dir> <output_file>", file=sys.stderr)
        sys.exit(1)
    evaluate(sys.argv[1], sys.argv[2])
