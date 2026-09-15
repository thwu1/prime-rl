#!/usr/bin/env python3
"""Fixed recommendation evaluation tool — RecBole-compatible metric semantics."""


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


def compute_hit(pos_indicator):
    return 1.0 if sum(pos_indicator) > 0 else 0.0


def compute_recall(pos_indicator, pos_len):
    if pos_len == 0:
        return 0.0
    return sum(pos_indicator) / pos_len


def compute_precision(pos_indicator):
    k = len(pos_indicator)
    if k == 0:
        return 0.0
    return sum(pos_indicator) / k


def compute_mrr(pos_indicator):
    # FIX: Return reciprocal rank of FIRST relevant item only
    for i, v in enumerate(pos_indicator):
        if v > 0:
            return 1.0 / (i + 1)
    return 0.0


def compute_ndcg(pos_indicator, pos_len):
    k = len(pos_indicator)
    if pos_len == 0 or k == 0:
        return 0.0
    dcg = sum(pos_indicator[i] / math.log2(i + 2) for i in range(k))
    # FIX: Cap IDCG length at min(pos_len, K)
    idcg_len = min(pos_len, k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(idcg_len))
    if idcg == 0:
        return 0.0
    return dcg / idcg


def compute_map(pos_indicator, pos_len):
    k = len(pos_indicator)
    if pos_len == 0 or k == 0:
        return 0.0
    cumsum = 0
    sum_prec = 0.0
    for i in range(k):
        cumsum += pos_indicator[i]
        if pos_indicator[i] > 0:
            sum_prec += cumsum / (i + 1)
    # FIX: Normalize by min(pos_len, K) instead of K
    actual_len = min(pos_len, k)
    if actual_len == 0:
        return 0.0
    return sum_prec / actual_len


def compute_item_coverage(all_top_k, num_items):
    unique = set()
    for items in all_top_k:
        unique.update(items)
    return len(unique) / num_items


def compute_gini_index(all_top_k, num_items):
    flat = []
    for items in all_top_k:
        flat.extend(items)
    if not flat:
        return 0.0
    cnt = Counter(flat)
    sorted_counts = sorted(cnt.values())
    num_recommended = len(sorted_counts)
    total_recs = len(flat)
    # FIX: Use num_items (full catalog) as population, not num_recommended
    gini = 0.0
    for i, c in enumerate(sorted_counts):
        idx = num_items - num_recommended + 1 + i
        gini += (2 * idx - num_items - 1) * c
    gini /= total_recs
    gini /= num_items
    return gini


def compute_shannon_entropy(all_top_k):
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
    # FIX: Normalize by count of unique items
    return entropy / len(cnt)


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

            # FIX: Only include users with non-empty relevant sets in per-user metrics
            if pos_len > 0:
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
