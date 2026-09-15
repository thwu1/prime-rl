#!/usr/bin/env python3

"""
PrivBayes-based differentially private synthetic tabular data generator.

Implements the algorithm from:
Zhang J, Cormode G, Procopiuc CM, Srivastava D, Xiao X.
PrivBayes: Private Data Release via Bayesian Networks. ACM TODS 2017.
"""

import argparse
import json
import os
import random
from bisect import bisect_right
from itertools import combinations, product
from math import log

import numpy as np
import pandas as pd
from sklearn.metrics import mutual_info_score


# ---------------------------------------------------------------------------
# Random seed management
# ---------------------------------------------------------------------------

def set_random_seed(seed):
    random.seed(seed)
    np.random.seed(seed)


# ---------------------------------------------------------------------------
# Distribution utilities
# ---------------------------------------------------------------------------

def normalize_distribution(dist):
    """Clip negative values to zero and normalize to sum to 1."""
    arr = np.array(dist, dtype=float)
    arr = np.clip(arr, 0, None)
    total = arr.sum()
    if total > 0:
        if np.isinf(total):
            return normalize_distribution(np.isinf(arr).astype(float))
        return (arr / total).tolist()
    else:
        n = len(arr)
        return [1.0 / n] * n


# ---------------------------------------------------------------------------
# Type inference
# ---------------------------------------------------------------------------

def infer_data_types(df, category_threshold=20):
    """Classify each column as Integer, Float, or String."""
    type_map = {}
    numerical_cols = set()

    # Use pandas describe to identify numerical columns
    describe = df.describe()
    if describe.shape[0] == 8:
        numerical_cols = set(describe.columns)

    for col in df.columns:
        col_dropna = df[col].dropna()
        if col in numerical_cols:
            if np.array_equal(col_dropna.values, col_dropna.astype(int, copy=False).values):
                type_map[col] = "Integer"
            else:
                type_map[col] = "Float"
        else:
            type_map[col] = "String"

    return type_map


def find_candidate_keys(df, type_map):
    """Integer columns with all unique values are candidate keys."""
    keys = set()
    for col in df.columns:
        if type_map[col] in ("Float",):
            continue
        if type_map[col] == "Integer" and df[col].dropna().is_unique:
            keys.add(col)
    return keys


def is_categorical(df, col, threshold=20):
    return df[col].dropna().nunique() <= threshold


# ---------------------------------------------------------------------------
# Attribute description
# ---------------------------------------------------------------------------

def build_attribute_descriptions(df, type_map, cat_map, candidate_keys):
    """Compute per-attribute metadata: bins, probabilities, min, max, etc."""
    attr_desc = {}
    for col in df.columns:
        col_data = df[col]
        col_dropna = col_data.dropna()
        is_cat = cat_map[col]
        is_key = col in candidate_keys
        missing_rate = float((col_data.size - col_dropna.size) / max(col_data.size, 1))

        if type_map[col] == "Integer":
            min_val = int(col_dropna.min())
            max_val = int(col_dropna.max())
        elif type_map[col] == "Float":
            min_val = float(col_dropna.min())
            max_val = float(col_dropna.max())
        else:
            # String type
            if is_cat:
                sorted_vals = sorted(col_dropna.unique().tolist())
                min_val = sorted_vals[0]
                max_val = sorted_vals[-1]
            else:
                lengths = col_dropna.astype(str).map(len)
                min_val = int(lengths.min())
                max_val = int(lengths.max())

        if is_cat:
            distribution = col_dropna.value_counts()
            for val in set(col_dropna.unique()) - set(distribution.index):
                distribution[val] = 0
            distribution.sort_index(inplace=True)
            bins = distribution.index.tolist()
            probs = normalize_distribution(distribution.values)
        else:
            if type_map[col] == "String":
                hist_data = col_dropna.astype(str).map(len)
            else:
                hist_data = col_dropna
            hist, bin_edges = np.histogram(hist_data, bins=20, range=(min_val, max_val))
            bins = bin_edges[:-1].tolist()
            probs = normalize_distribution(hist)

        attr_desc[col] = {
            "name": col,
            "data_type": type_map[col],
            "is_categorical": is_cat,
            "is_candidate_key": is_key,
            "min": min_val,
            "max": max_val,
            "missing_rate": missing_rate,
            "distribution_bins": bins,
            "distribution_probabilities": probs,
        }
    return attr_desc


# ---------------------------------------------------------------------------
# Laplace noise for marginal distributions
# ---------------------------------------------------------------------------

def inject_laplace_noise_marginals(attr_desc, bn_attrs, epsilon_half, n):
    """Inject Laplace noise into marginal distributions of BN attributes."""
    num_bn = len(bn_attrs)
    for col in bn_attrs:
        probs = attr_desc[col]["distribution_probabilities"]
        sensitivity = 2.0 / n
        eps_per_attr = epsilon_half / num_bn
        if eps_per_attr > 0:
            noise_scale = sensitivity / eps_per_attr
            noisy = np.array(probs) + np.random.laplace(0, noise_scale, len(probs))
            attr_desc[col]["distribution_probabilities"] = normalize_distribution(noisy)


# ---------------------------------------------------------------------------
# Encoding columns into bin indices
# ---------------------------------------------------------------------------

def encode_column(series, bins, is_cat):
    """Encode a pandas Series into bin indices."""
    if is_cat:
        val_to_idx = {v: i for i, v in enumerate(bins)}
        encoded = series.map(lambda x: val_to_idx.get(x, len(bins)), na_action="ignore")
    else:
        encoded = series.map(lambda x: bisect_right(bins, x) - 1, na_action="ignore")
    encoded.fillna(len(bins), inplace=True)
    return encoded.astype(int)


def build_encoded_dataset(df, attr_desc, bn_attrs):
    """Encode the BN attributes into bin indices."""
    encoded = pd.DataFrame()
    for col in bn_attrs:
        encoded[col] = encode_column(
            df[col],
            attr_desc[col]["distribution_bins"],
            attr_desc[col]["is_categorical"],
        )
    return encoded


# ---------------------------------------------------------------------------
# Mutual information
# ---------------------------------------------------------------------------

def compute_mutual_information(labels_x, labels_y_df):
    """Compute MI between a child column and parent columns."""
    if isinstance(labels_y_df, pd.DataFrame):
        if labels_y_df.shape[1] == 1:
            labels_y = labels_y_df.iloc[:, 0]
        else:
            labels_y = labels_y_df.apply(lambda row: " ".join(row.astype(str)), axis=1)
    else:
        labels_y = labels_y_df
    return mutual_info_score(labels_x.astype(str), labels_y.astype(str))


# ---------------------------------------------------------------------------
# PrivBayes sensitivity (Lemma 1)
# ---------------------------------------------------------------------------

def calculate_sensitivity(n, child, parents, attr_to_is_binary):
    """Sensitivity for the exponential mechanism per PrivBayes Lemma 1."""
    if attr_to_is_binary[child] or (len(parents) == 1 and attr_to_is_binary[parents[0]]):
        a = log(n) / n
        b = (n - 1) / n
        b_inv = n / (n - 1)
        return a + b * log(b_inv)
    else:
        a = (2.0 / n) * log((n + 1) / 2.0)
        b = (1.0 - 1.0 / n) * log(1 + 2.0 / (n - 1))
        return a + b


def calculate_delta(num_attributes, sensitivity, epsilon):
    return (num_attributes - 1) * sensitivity / epsilon


# ---------------------------------------------------------------------------
# Exponential mechanism
# ---------------------------------------------------------------------------

def exponential_mechanism(epsilon, mi_list, pair_list, attr_to_is_binary, n, d):
    """Sample (child, parents) via exponential mechanism with MI as score."""
    delta_array = []
    for child, parents in pair_list:
        sens = calculate_sensitivity(n, child, parents, attr_to_is_binary)
        delta = calculate_delta(d, sens, epsilon)
        delta_array.append(delta)

    scores = np.array(mi_list) / (2.0 * np.array(delta_array))
    scores = np.exp(scores)
    total = scores.sum()
    if total > 0 and not np.isinf(total):
        return scores / total
    else:
        return np.ones(len(scores)) / len(scores)


# ---------------------------------------------------------------------------
# Greedy Bayesian network construction
# ---------------------------------------------------------------------------

def greedy_bayes(encoded_df, k, epsilon, seed=0):
    """Build BN by greedily adding attributes via exponential mechanism."""
    set_random_seed(seed)
    encoded_str = encoded_df.astype(str, copy=False)
    n, d = encoded_str.shape

    if k <= 0:
        k = min(3, d - 1)

    attr_to_is_binary = {attr: encoded_str[attr].nunique() <= 2 for attr in encoded_str}

    root = random.choice(list(encoded_str.columns))
    V = [root]
    rest = list(encoded_str.columns)
    rest.remove(root)

    N = []
    while rest:
        pair_list = []
        mi_list = []
        num_parents = min(len(V), k)

        for child in rest:
            for combo in combinations(V, num_parents):
                parents = list(combo)
                mi = compute_mutual_information(encoded_str[child], encoded_str[parents])
                pair_list.append((child, parents))
                mi_list.append(mi)

        if epsilon > 0 and mi_list:
            sampling_dist = exponential_mechanism(
                epsilon, mi_list, pair_list, attr_to_is_binary, n, d
            )
            idx = np.random.choice(len(mi_list), p=sampling_dist)
        else:
            idx = mi_list.index(max(mi_list))

        selected = pair_list[idx]
        N.append(selected)
        new_attr = selected[0]
        V.append(new_attr)
        rest.remove(new_attr)

    return N


# ---------------------------------------------------------------------------
# Noisy conditional distributions
# ---------------------------------------------------------------------------

def laplace_noise_scale(k, num_attributes, epsilon):
    """Noise scale for conditional distributions per PrivBayes."""
    return (num_attributes - k) / epsilon


def get_noisy_joint_distribution(attributes, encoded_df, epsilon):
    """Compute noisy joint distribution of the given attributes."""
    data = encoded_df[attributes].copy()
    data["count"] = 1
    stats = data.groupby(attributes).sum()

    # Build full cross-product space
    iterables = [range(int(encoded_df[attr].max()) + 1) for attr in attributes]
    full_space = pd.DataFrame(list(product(*iterables)), columns=attributes)

    stats.reset_index(inplace=True)
    stats = pd.merge(full_space, stats, how="left")
    stats.fillna(0, inplace=True)

    if epsilon > 0:
        k_parents = len(attributes) - 1
        num_attrs = encoded_df.shape[1]
        noise_para = laplace_noise_scale(k_parents, num_attrs, epsilon)
        noises = np.random.laplace(0, scale=noise_para, size=len(stats))
        stats["count"] += noises
        stats.loc[stats["count"] < 0, "count"] = 0

    return stats


def construct_conditional_distributions(bn, encoded_df, epsilon):
    """Construct noisy conditional probability tables per PrivBayes Algorithm 1."""
    k = len(bn[-1][1])  # max parent count (from last entry)
    cond_dist = {}

    # Identify root and first k+1 attributes
    root = bn[0][1][0]
    kplus1_attrs = [root]
    for child, _ in bn[:k]:
        kplus1_attrs.append(child)

    # Joint noisy distribution of first k+1 attributes
    noisy_joint = get_noisy_joint_distribution(kplus1_attrs, encoded_df, epsilon)

    # Root marginal
    root_stats = noisy_joint[[root, "count"]].groupby(root).sum()["count"]
    cond_dist[root] = normalize_distribution(root_stats.values)

    for idx, (child, parents) in enumerate(bn):
        cond_dist[child] = {}

        if idx <= k - 2:
            # Use subset of the joint
            stats = noisy_joint[parents + [child, "count"]].copy()
            stats = stats.groupby(parents + [child], as_index=False).sum()
        elif idx == k - 1:
            stats = noisy_joint[parents + [child, "count"]]
        else:
            # Compute fresh pairwise noisy distribution
            stats = get_noisy_joint_distribution(parents + [child], encoded_df, epsilon)
            stats = stats[parents + [child, "count"]]

        # Group by parent values and compute conditional distributions
        parent_key = parents[0] if len(parents) == 1 else parents
        for parent_vals, sub_df in stats.groupby(parent_key):
            sub_df = sub_df.sort_values(by=child)
            dist = normalize_distribution(sub_df["count"].values)
            if len(parents) == 1:
                key_str = str([int(parent_vals)])
            else:
                key_str = str([int(x) for x in parent_vals])
            cond_dist[child][key_str] = dist

    return cond_dist


# ---------------------------------------------------------------------------
# Synthetic data generation
# ---------------------------------------------------------------------------

def get_sampling_order(bn):
    """Get the topological order of BN attributes."""
    root = bn[0][1][0]
    order = [root]
    for child, _ in bn:
        order.append(child)
    return order


def generate_encoded_synthetic(bn, cond_probs, attr_desc, n):
    """Ancestrally sample bin indices from the BN."""
    order = get_sampling_order(bn)
    root = order[0]

    encoded = pd.DataFrame(columns=order)
    root_dist = cond_probs[root]
    encoded[root] = np.random.choice(len(root_dist), size=n, p=root_dist)

    for child, parents in bn:
        child_cond = cond_probs[child]

        for key_str, dist in child_cond.items():
            parent_vals = eval(key_str)
            if len(parents) == 1:
                mask = encoded[parents[0]] == parent_vals[0]
            else:
                mask = pd.Series(True, index=encoded.index)
                for p, v in zip(parents, parent_vals):
                    mask &= encoded[p] == v

            size = int(mask.sum())
            if size > 0:
                encoded.loc[mask, child] = np.random.choice(len(dist), size=size, p=dist)

        # Fill any unassigned rows with marginal distribution
        null_mask = encoded[child].isnull()
        if null_mask.any():
            uncond = attr_desc[child]["distribution_probabilities"]
            encoded.loc[null_mask, child] = np.random.choice(
                len(uncond), size=int(null_mask.sum()), p=uncond
            )

    encoded[encoded.columns] = encoded[encoded.columns].astype(int)
    return encoded


def decode_bin_indices(encoded_df, attr_desc, all_columns, candidate_keys, bn_attrs, n):
    """Convert bin indices back to actual values."""
    synthetic = pd.DataFrame(columns=all_columns)

    for col in all_columns:
        info = attr_desc[col]
        bins = info["distribution_bins"]
        is_cat = info["is_categorical"]
        is_key = info["is_candidate_key"]
        dtype = info["data_type"]

        if is_key:
            synthetic[col] = list(range(n))
        elif col in encoded_df.columns:
            if is_cat:
                synthetic[col] = encoded_df[col].map(
                    lambda x: bins[x] if x < len(bins) else np.nan
                )
            else:
                def _sample_bin(idx, b=bins, mx=info["max"]):
                    if idx >= len(b):
                        return np.nan
                    elif idx < len(b) - 1:
                        return random.uniform(b[idx], b[idx + 1])
                    else:
                        return random.uniform(b[idx], mx)

                synthetic[col] = encoded_df[col].map(_sample_bin)
                if dtype == "Integer":
                    non_null = ~synthetic[col].isnull()
                    synthetic.loc[non_null, col] = synthetic.loc[non_null, col].round().astype(int)
        else:
            # Non-BN, non-key: sample independently from marginal
            probs = info["distribution_probabilities"]
            indices = np.random.choice(len(probs), size=n, p=probs)
            if is_cat:
                synthetic[col] = [bins[i] for i in indices]
            else:
                vals = []
                for i in indices:
                    if i < len(bins) - 1:
                        vals.append(random.uniform(bins[i], bins[i + 1]))
                    else:
                        vals.append(random.uniform(bins[i], info["max"]))
                synthetic[col] = vals
                if dtype == "Integer":
                    synthetic[col] = synthetic[col].round().astype(int)

    return synthetic


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="PrivBayes synthetic data generator")
    parser.add_argument("--input", required=True, help="Input CSV path")
    parser.add_argument("--epsilon", type=float, required=True, help="Privacy budget")
    parser.add_argument("--max-parents", type=int, required=True, help="Max BN parents")
    parser.add_argument("--seed", type=int, required=True, help="Random seed")
    parser.add_argument("--num-rows", type=int, required=True, help="Number of synthetic rows")
    parser.add_argument("--output-desc", required=True, help="Output description JSON path")
    parser.add_argument("--output-csv", required=True, help="Output synthetic CSV path")
    args = parser.parse_args()

    set_random_seed(args.seed)

    # Read input
    df = pd.read_csv(
        args.input,
        skipinitialspace=True,
        na_values=["", "NULL", "N/A", "NA", "NaN", "nan"],
    )

    # Infer types
    type_map = infer_data_types(df)

    # Find candidate keys and categorical attributes
    candidate_keys = find_candidate_keys(df, type_map)
    cat_map = {col: is_categorical(df, col) for col in df.columns}

    # Determine attributes in BN
    non_cat_strings = {
        col for col in df.columns
        if not cat_map[col] and type_map[col] == "String"
    }
    bn_attrs = [
        col for col in df.columns
        if col not in candidate_keys and col not in non_cat_strings
    ]

    # Build attribute descriptions
    attr_desc = build_attribute_descriptions(df, type_map, cat_map, candidate_keys)

    # Inject noise into marginal distributions
    epsilon_half = args.epsilon / 2.0
    n = df.shape[0]
    inject_laplace_noise_marginals(attr_desc, bn_attrs, epsilon_half, n)

    # Encode dataset for BN construction
    encoded_df = build_encoded_dataset(df, attr_desc, bn_attrs)

    # Build Bayesian network
    bn = greedy_bayes(encoded_df, args.max_parents, epsilon_half, seed=args.seed)

    # Compute conditional distributions
    cond_probs = construct_conditional_distributions(bn, encoded_df, epsilon_half)

    # Build description
    description = {
        "meta": {
            "num_tuples": int(df.shape[0]),
            "num_attributes": int(df.shape[1]),
            "all_attributes": df.columns.tolist(),
            "candidate_keys": sorted(list(candidate_keys)),
            "attributes_in_BN": bn_attrs,
        },
        "attribute_description": attr_desc,
        "bayesian_network": [[child, parents] for child, parents in bn],
        "conditional_probabilities": cond_probs,
    }

    # Generate synthetic data
    set_random_seed(args.seed)
    encoded_synthetic = generate_encoded_synthetic(bn, cond_probs, attr_desc, args.num_rows)
    synthetic_df = decode_bin_indices(
        encoded_synthetic, attr_desc, df.columns.tolist(), candidate_keys, bn_attrs, args.num_rows
    )

    # Save outputs
    os.makedirs(os.path.dirname(os.path.abspath(args.output_desc)), exist_ok=True)
    with open(args.output_desc, "w") as f:
        json.dump(description, f, indent=4)
    synthetic_df.to_csv(args.output_csv, index=False)


if __name__ == "__main__":
    main()
