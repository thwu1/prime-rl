#!/usr/bin/env python3
"""
Correct partition evaluation for DC-SBM network.

Fixes all issues in the buggy pipeline:
1. Uses directed (asymmetric) inter-block edge matrix
2. Includes N*ln(B) term in model entropy
3. Uses Hungarian algorithm for optimal label matching
4. Uses arithmetic mean NMI normalization

"""
import json
import os
import math
import numpy as np
from scipy.optimize import linear_sum_assignment

GRAPH_PATH = '/app/data/network.tsv'
TRUTH_PATH = '/app/data/ground_truth.tsv'
DETECTIONS_DIR = '/app/data/detections'
OUTPUT_PATH = '/app/results.json'
CANDIDATE_IDS = ['A', 'B', 'C', 'D', 'E', 'F']


def load_graph(path):
    edges = []
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) >= 3:
                edges.append((int(parts[0]), int(parts[1]), int(parts[2])))
    return edges


def load_partition(path):
    data = []
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\t')
            data.append((int(parts[0]) - 1, int(parts[1])))
    N = max(n for n, _ in data) + 1
    raw_labels = [0] * N
    for n, b in data:
        raw_labels[n] = b
    unique_labels = sorted(set(raw_labels))
    label_map = {l: i for i, l in enumerate(unique_labels)}
    return np.array([label_map[raw_labels[i]] for i in range(N)])


def interblock_matrix(edges, partition):
    B = int(partition.max()) + 1
    M = np.zeros((B, B), dtype=int)
    for src, dst, w in edges:
        r = partition[src - 1]
        s = partition[dst - 1]
        M[r, s] += w
    return M


def compute_description_length(edges, partition, N):
    M = interblock_matrix(edges, partition)
    B = M.shape[0]
    E = sum(w for _, _, w in edges)

    d_out = M.sum(axis=1).astype(float)
    d_in = M.sum(axis=0).astype(float)

    x = float(B ** 2) / float(E)
    S_model = E * ((1.0 + x) * math.log(1.0 + x) - x * math.log(x)) + N * math.log(B)

    nz = M.nonzero()
    if len(nz[0]) == 0:
        S_data = 0.0
    else:
        M_vals = M[nz[0], nz[1]].astype(float)
        d_out_vals = d_out[nz[0]]
        d_in_vals = d_in[nz[1]]
        S_data = -float(np.sum(M_vals * np.log(M_vals / (d_out_vals * d_in_vals))))

    return S_model + S_data


def compute_accuracy(true_part, pred_part):
    B_t = int(true_part.max()) + 1
    B_p = int(pred_part.max()) + 1
    C = np.zeros((B_t, B_p), dtype=int)
    for i in range(len(true_part)):
        C[true_part[i], pred_part[i]] += 1

    row_ind, col_ind = linear_sum_assignment(-C)
    correct = C[row_ind, col_ind].sum()
    return float(correct) / float(len(true_part))


def compute_ari(true_part, pred_part):
    B_t = int(true_part.max()) + 1
    B_p = int(pred_part.max()) + 1
    N = len(true_part)
    C = np.zeros((B_t, B_p), dtype=float)
    for i in range(N):
        C[true_part[i], pred_part[i]] += 1.0
    a = C.sum(axis=1)
    b = C.sum(axis=0)

    def comb2(x):
        return x * (x - 1.0) / 2.0

    sum_comb_nij = sum(comb2(C[i, j]) for i in range(B_t) for j in range(B_p))
    sum_comb_a = sum(comb2(ai) for ai in a)
    sum_comb_b = sum(comb2(bj) for bj in b)
    comb_N = comb2(float(N))

    expected = sum_comb_a * sum_comb_b / comb_N
    max_index = (sum_comb_a + sum_comb_b) / 2.0
    if max_index == expected:
        return 1.0
    return (sum_comb_nij - expected) / (max_index - expected)


def compute_nmi(true_part, pred_part):
    N = len(true_part)
    B_t = int(true_part.max()) + 1
    B_p = int(pred_part.max()) + 1
    C = np.zeros((B_t, B_p), dtype=float)
    for i in range(N):
        C[true_part[i], pred_part[i]] += 1.0
    joint = C / float(N)
    p_t = joint.sum(axis=1)
    p_p = joint.sum(axis=0)

    H_t = -sum(p * math.log(p) for p in p_t if p > 0)
    H_p = -sum(p * math.log(p) for p in p_p if p > 0)
    MI = sum(joint[i, j] * math.log(joint[i, j] / (p_t[i] * p_p[j]))
             for i in range(B_t) for j in range(B_p) if joint[i, j] > 0)

    if H_t + H_p == 0:
        return 1.0
    return 2.0 * MI / (H_t + H_p)


def main():
    edges = load_graph(GRAPH_PATH)
    truth = load_partition(TRUTH_PATH)
    N = len(truth)

    desc_lengths = {}
    desc_lengths['truth'] = compute_description_length(edges, truth, N)

    candidates = {}
    for cid in CANDIDATE_IDS:
        path = os.path.join(DETECTIONS_DIR, 'result_{}.tsv'.format(cid))
        part = load_partition(path)
        candidates[cid] = part
        desc_lengths[cid] = compute_description_length(edges, part, N)

    cand_lengths = {c: desc_lengths[c] for c in CANDIDATE_IDS}
    best = min(cand_lengths, key=cand_lengths.get)
    ranking = sorted(CANDIDATE_IDS, key=lambda c: cand_lengths[c])

    comparison = {}
    for cid in CANDIDATE_IDS:
        comparison[cid] = {
            'accuracy': compute_accuracy(truth, candidates[cid]),
            'ari': compute_ari(truth, candidates[cid]),
            'nmi': compute_nmi(truth, candidates[cid]),
        }

    results = {
        'description_lengths': desc_lengths,
        'best_partition': best,
        'ranking': ranking,
        'comparison_metrics': comparison,
    }

    with open(OUTPUT_PATH, 'w') as f:
        json.dump(results, f, indent=2)

    print('Results written to', OUTPUT_PATH)


if __name__ == '__main__':
    main()
