"""Metrics for partition evaluation on DC-SBM networks.

References:
    Peixoto, T.P. "Entropy of stochastic blockmodel ensembles."
    Physical Review E 85, no. 5 (2012): 056122.
"""
import math
import numpy as np


def load_graph(path):
    """Load directed graph from TSV (source, destination, weight)."""
    edges = []
    with open(path) as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) >= 3:
                edges.append((int(parts[0]), int(parts[1]), int(parts[2])))
    return edges


def load_partition(path):
    """Load partition from TSV (node, block). Remap to 0-based consecutive labels."""
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


def _interblock_matrix(edges, partition):
    """Compute inter-block edge count matrix M[r,s]."""
    B = int(partition.max()) + 1
    M = np.zeros((B, B), dtype=int)
    for src, dst, w in edges:
        r = partition[src - 1]
        s = partition[dst - 1]
        M[r, s] += w
        M[s, r] += w  # symmetrize for undirected analysis
    return M


def compute_description_length(edges, partition, N):
    """Compute DC-SBM description length for a partition.

    S = S_model + S_data
    S_model encodes the model complexity.
    S_data encodes the data given the model.
    """
    M = _interblock_matrix(edges, partition)
    B = M.shape[0]
    E = sum(w for _, _, w in edges)

    d_out = M.sum(axis=1).astype(float)
    d_in = M.sum(axis=0).astype(float)

    x = float(B ** 2) / float(E)
    S_model = E * ((1.0 + x) * math.log(1.0 + x) - x * math.log(x))

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
    """Classification accuracy with label matching."""
    B_t = int(true_part.max()) + 1
    B_p = int(pred_part.max()) + 1
    C = np.zeros((B_t, B_p), dtype=int)
    for i in range(len(true_part)):
        C[true_part[i], pred_part[i]] += 1

    # Greedy matching: assign each true label to its best available pred label
    correct = 0
    used_cols = set()
    for i in range(B_t):
        best_j = -1
        best_count = -1
        for j in range(B_p):
            if j not in used_cols and C[i, j] > best_count:
                best_count = C[i, j]
                best_j = j
        if best_j >= 0:
            correct += C[i, best_j]
            used_cols.add(best_j)
    return float(correct) / float(len(true_part))


def compute_ari(true_part, pred_part):
    """Adjusted Rand Index from contingency table."""
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
    """Normalized Mutual Information."""
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
    return MI / max(H_t, H_p)
