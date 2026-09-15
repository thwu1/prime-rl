#!/usr/bin/env python3

"""Sparse matrix format conversion, analysis, and format recommendation pipeline.

Corrected version with all six fixes applied:
1. JDS col_start loop: range(max_row_nnz) instead of range(max_row_nnz - 1)
2. RCM un-permutation: rcm_jds_result[rcm_perm[new_i]] = rcm_jds_permuted[new_i]
3. Reordered bandwidth: computed on rcm_row_ptr/rcm_col_idx, not original
4. ELLPACK layout: row-major (i * max_nnz + k) matching SpMV access pattern
5. Profile: accumulates sum of envelopes, not max
6. Format scoring: JDS benefits from high CV, ELLPACK from low CV
"""

import sys
import json
import os
from collections import deque


def read_csr(data_dir):
    """Read sparse matrix in CSR raw file format and input vector."""
    with open(os.path.join(data_dir, "row.raw")) as f:
        n = int(f.readline().strip())
        row_ptr = [int(f.readline().strip()) for _ in range(n)]

    with open(os.path.join(data_dir, "col.raw")) as f:
        n = int(f.readline().strip())
        col_idx = [int(f.readline().strip()) for _ in range(n)]

    with open(os.path.join(data_dir, "data.raw")) as f:
        n = int(f.readline().strip())
        values = [float(f.readline().strip()) for _ in range(n)]

    with open(os.path.join(data_dir, "vec.raw")) as f:
        dim = int(f.readline().strip())
        vec = [float(f.readline().strip()) for _ in range(dim)]

    return row_ptr, col_idx, values, vec, dim


def csr_spmv(row_ptr, col_idx, values, vec, dim):
    """Compute y = A*x using CSR format."""
    result = [0.0] * dim
    for i in range(dim):
        s = 0.0
        for j in range(row_ptr[i], row_ptr[i + 1]):
            s += values[j] * vec[col_idx[j]]
        result[i] = s
    return result


def csr_to_jds(row_ptr, col_idx, values, dim):
    """Convert CSR to JDS (Jagged Diagonal Storage).

    Returns (jds_col_idx, jds_data, col_start, row_perm).
    """
    nnz_per_row = [row_ptr[i + 1] - row_ptr[i] for i in range(dim)]

    row_perm = sorted(range(dim), key=lambda i: (-nnz_per_row[i], i))
    sorted_nnz = [nnz_per_row[row_perm[i]] for i in range(dim)]

    if dim == 0 or sorted_nnz[0] == 0:
        return [], [], [0], row_perm

    max_row_nnz = sorted_nnz[0]

    # FIX 1: iterate max_row_nnz times (not max_row_nnz - 1)
    col_start = [0]
    for col in range(max_row_nnz):
        count = sum(1 for idx in range(dim) if sorted_nnz[idx] > col)
        col_start.append(col_start[-1] + count)

    total_nnz = row_ptr[dim] if dim > 0 else 0
    jds_col = [0] * total_nnz
    jds_data = [0.0] * total_nnz

    for idx in range(dim):
        row = row_perm[idx]
        rnnz = sorted_nnz[idx]
        for k in range(rnnz):
            jds_pos = col_start[k] + idx
            csr_pos = row_ptr[row] + k
            jds_col[jds_pos] = col_idx[csr_pos]
            jds_data[jds_pos] = values[csr_pos]

    return jds_col, jds_data, col_start, row_perm


def jds_spmv(jds_col, jds_data, col_start, row_perm, vec, dim):
    """Compute y = A*x using JDS format. Result in original row ordering."""
    result = [0.0] * dim
    max_col = len(col_start) - 1

    for col in range(max_col):
        num_rows = col_start[col + 1] - col_start[col]
        for idx in range(num_rows):
            pos = col_start[col] + idx
            result[row_perm[idx]] += jds_data[pos] * vec[jds_col[pos]]

    return result


def csr_to_ell(row_ptr, col_idx, values, dim):
    """Convert CSR to ELLPACK format.

    Returns (ell_col, ell_data, max_nnz_per_row).
    ell_col and ell_data are flat arrays of size dim * max_nnz_per_row.
    Padded positions have col=0 and data=0.0.
    """
    nnz_per_row = [row_ptr[i + 1] - row_ptr[i] for i in range(dim)]
    max_nnz = max(nnz_per_row) if dim > 0 else 0

    if max_nnz == 0:
        return [], [], 0

    ell_col = [0] * (dim * max_nnz)
    ell_data = [0.0] * (dim * max_nnz)

    for i in range(dim):
        for k in range(nnz_per_row[i]):
            # FIX 4: row-major layout matching SpMV access pattern
            pos = i * max_nnz + k
            csr_pos = row_ptr[i] + k
            ell_col[pos] = col_idx[csr_pos]
            ell_data[pos] = values[csr_pos]

    return ell_col, ell_data, max_nnz


def ell_spmv(ell_col, ell_data, max_nnz, vec, dim):
    """Compute y = A*x using ELLPACK format."""
    result = [0.0] * dim
    for i in range(dim):
        s = 0.0
        for k in range(max_nnz):
            pos = i * max_nnz + k
            s += ell_data[pos] * vec[ell_col[pos]]
        result[i] = s
    return result


def compute_bandwidth(row_ptr, col_idx, dim):
    """Compute matrix bandwidth: max |i - j| over all non-zero A[i][j]."""
    bw = 0
    for i in range(dim):
        for j in range(row_ptr[i], row_ptr[i + 1]):
            bw = max(bw, abs(i - col_idx[j]))
    return bw


def compute_profile(row_ptr, col_idx, dim):
    """Compute matrix profile (envelope size).

    Profile = sum over all rows i of max(0, i - min_col_in_row_i).
    """
    profile = 0
    for i in range(dim):
        if row_ptr[i] < row_ptr[i + 1]:
            min_col = min(col_idx[j] for j in range(row_ptr[i], row_ptr[i + 1]))
            envelope = i - min_col
            if envelope > 0:
                # FIX 5: accumulate sum, not max
                profile += envelope
    return profile


def build_symmetric_adjacency(row_ptr, col_idx, dim):
    """Build symmetrized adjacency lists (excluding self-loops)."""
    adj = [set() for _ in range(dim)]
    for i in range(dim):
        for j in range(row_ptr[i], row_ptr[i + 1]):
            c = col_idx[j]
            if c != i:
                adj[i].add(c)
                adj[c].add(i)
    return [sorted(s) for s in adj]


def find_pseudo_peripheral(adj, component, comp_set):
    """Find a pseudo-peripheral node via iterated BFS eccentricity."""
    if len(component) <= 1:
        return component[0]

    def comp_degree(n):
        return sum(1 for nb in adj[n] if nb in comp_set)

    start = min(component, key=comp_degree)
    best_eccentricity = -1

    for _ in range(10):
        dist = {start: 0}
        queue = deque([start])
        max_dist = 0

        while queue:
            node = queue.popleft()
            for nb in adj[node]:
                if nb in comp_set and nb not in dist:
                    dist[nb] = dist[node] + 1
                    if dist[nb] > max_dist:
                        max_dist = dist[nb]
                    queue.append(nb)

        if max_dist <= best_eccentricity:
            break
        best_eccentricity = max_dist

        last_level = [n for n in dist if dist[n] == max_dist]
        new_start = min(last_level, key=comp_degree)
        if new_start == start:
            break
        start = new_start

    return start


def rcm_ordering(row_ptr, col_idx, dim):
    """Compute Reverse Cuthill-McKee ordering.

    Returns perm where perm[new_index] = original_index.
    Handles disconnected components independently.
    """
    adj = build_symmetric_adjacency(row_ptr, col_idx, dim)

    global_visited = set()
    order = []

    for seed in range(dim):
        if seed in global_visited:
            continue

        component = []
        stack = [seed]
        comp_visited = {seed}
        while stack:
            node = stack.pop()
            component.append(node)
            for nb in adj[node]:
                if nb not in comp_visited:
                    comp_visited.add(nb)
                    stack.append(nb)

        comp_set = frozenset(component)
        global_visited.update(comp_set)

        if len(component) == 1:
            order.append(seed)
            continue

        start = find_pseudo_peripheral(adj, component, comp_set)

        def comp_degree(n):
            return sum(1 for nb in adj[n] if nb in comp_set)

        bfs_visited = {start}
        queue = deque([start])
        comp_order = []

        while queue:
            node = queue.popleft()
            comp_order.append(node)
            neighbors = sorted(
                [nb for nb in adj[node] if nb in comp_set and nb not in bfs_visited],
                key=comp_degree,
            )
            for nb in neighbors:
                bfs_visited.add(nb)
                queue.append(nb)

        order.extend(comp_order)

    order.reverse()
    return order


def apply_symmetric_permutation(row_ptr, col_idx, values, perm, dim):
    """Apply symmetric permutation P*A*P^T where perm[new] = old.

    Returns (new_row_ptr, new_col_idx, new_values) in CSR format
    with column indices sorted within each row.
    """
    inv_perm = [0] * dim
    for new_i, old_i in enumerate(perm):
        inv_perm[old_i] = new_i

    new_rows_data = [[] for _ in range(dim)]
    for new_i in range(dim):
        old_i = perm[new_i]
        for j in range(row_ptr[old_i], row_ptr[old_i + 1]):
            new_j = inv_perm[col_idx[j]]
            new_rows_data[new_i].append((new_j, values[j]))

    new_row_ptr = [0]
    new_col_idx = []
    new_values = []
    for i in range(dim):
        entries = sorted(new_rows_data[i])
        for c, v in entries:
            new_col_idx.append(c)
            new_values.append(v)
        new_row_ptr.append(len(new_col_idx))

    return new_row_ptr, new_col_idx, new_values


def compute_format_scores(row_ptr, col_idx, dim):
    """Compute quality scores for each sparse format.

    Returns (scores_dict, matrix_stats_dict).
    """
    nnz = row_ptr[dim] if dim > 0 else 0
    nnz_per_row = [row_ptr[i + 1] - row_ptr[i] for i in range(dim)]
    max_nnz = max(nnz_per_row) if dim > 0 else 0
    mean_nnz = nnz / dim if dim > 0 else 0.0

    if dim > 0 and mean_nnz > 0:
        variance = sum((r - mean_nnz) ** 2 for r in nnz_per_row) / dim
        cv = (variance ** 0.5) / mean_nnz
    else:
        cv = 0.0

    ell_total = dim * max_nnz if dim > 0 and max_nnz > 0 else 0
    ell_fill = nnz / ell_total if ell_total > 0 else 0.0

    dense = dim * dim if dim > 0 else 1
    csr_mem = nnz * 2 + dim + 1
    jds_mem = nnz * 2 + max_nnz + 1 + dim
    ell_mem = ell_total * 2

    csr_eff = 0.6
    # FIX 6: JDS benefits from high CV, ELLPACK from low CV
    jds_eff = 0.5 + 0.4 * min(cv, 1.0)
    ell_eff = (0.5 + 0.4 * (1.0 - min(cv, 1.0))) * ell_fill

    scores = {
        "CSR": {
            "storage_ratio": round(csr_mem / dense, 6),
            "efficiency": round(csr_eff, 6),
        },
        "JDS": {
            "storage_ratio": round(jds_mem / dense, 6),
            "efficiency": round(jds_eff, 6),
        },
        "ELL": {
            "storage_ratio": round(ell_mem / dense, 6),
            "efficiency": round(ell_eff, 6),
        },
    }

    ranked = sorted(scores.keys(), key=lambda f: -scores[f]["efficiency"])
    for rank, fmt in enumerate(ranked, 1):
        scores[fmt]["recommended_rank"] = rank

    return scores, {
        "cv": round(cv, 6),
        "ell_fill_ratio": round(ell_fill, 6),
        "max_nnz_per_row": max_nnz,
        "mean_nnz_per_row": round(mean_nnz, 6),
    }


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <data_dir> <output.json>", file=sys.stderr)
        sys.exit(1)

    data_dir = sys.argv[1]
    output_path = sys.argv[2]

    row_ptr, col_idx, values, vec, dim = read_csr(data_dir)

    csr_result = csr_spmv(row_ptr, col_idx, values, vec, dim)

    jds_col, jds_data, col_start, row_perm = csr_to_jds(
        row_ptr, col_idx, values, dim
    )
    jds_result = jds_spmv(jds_col, jds_data, col_start, row_perm, vec, dim)

    ell_col, ell_data, max_nnz = csr_to_ell(row_ptr, col_idx, values, dim)
    ell_result = ell_spmv(ell_col, ell_data, max_nnz, vec, dim)

    rcm_perm = rcm_ordering(row_ptr, col_idx, dim)

    rcm_row_ptr, rcm_col_idx, rcm_values = apply_symmetric_permutation(
        row_ptr, col_idx, values, rcm_perm, dim
    )
    rcm_vec = [vec[rcm_perm[i]] for i in range(dim)]

    rcm_jds_col, rcm_jds_data, rcm_col_start, rcm_jds_rperm = csr_to_jds(
        rcm_row_ptr, rcm_col_idx, rcm_values, dim
    )
    rcm_jds_permuted = jds_spmv(
        rcm_jds_col, rcm_jds_data, rcm_col_start, rcm_jds_rperm, rcm_vec, dim
    )

    # FIX 2: correct un-permutation direction
    rcm_jds_result = [0.0] * dim
    for new_i in range(dim):
        rcm_jds_result[rcm_perm[new_i]] = rcm_jds_permuted[new_i]

    bw_orig = compute_bandwidth(row_ptr, col_idx, dim)
    # FIX 3: compute bandwidth on the reordered matrix
    bw_rcm = compute_bandwidth(rcm_row_ptr, rcm_col_idx, dim)

    profile_orig = compute_profile(row_ptr, col_idx, dim)
    profile_rcm = compute_profile(rcm_row_ptr, rcm_col_idx, dim)

    format_scores, matrix_stats = compute_format_scores(row_ptr, col_idx, dim)

    report = {
        "dimension": dim,
        "nnz": row_ptr[dim] if dim > 0 else 0,
        "csr_spmv": csr_result,
        "jds_spmv": jds_result,
        "ell_spmv": ell_result,
        "jds_row_perm": row_perm,
        "jds_col_start": col_start,
        "rcm_perm": rcm_perm,
        "bandwidth_original": bw_orig,
        "bandwidth_reordered": bw_rcm,
        "profile_original": profile_orig,
        "profile_reordered": profile_rcm,
        "rcm_jds_spmv": rcm_jds_result,
        "format_scores": format_scores,
        "matrix_stats": matrix_stats,
    }

    out_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(out_dir, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
