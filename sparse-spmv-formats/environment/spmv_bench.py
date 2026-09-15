#!/usr/bin/env python3
"""Sparse matrix performance benchmarking tool.

Analyzes sparse matrix storage formats for GPU SpMV performance.
Supports CSR, JDS (Jagged Diagonal Storage), and ELLPACK formats.
"""

import os


def load_mtx(filepath):
    """Load a Matrix Market coordinate format file and return CSR arrays.

    Returns: (row_ptr, col_idx, data, num_rows, num_cols, nnz)
    """
    raise NotImplementedError("Matrix Market loading not yet implemented")


def load_csr_dir(dirpath):
    """Load CSR matrix from a directory containing text files.

    Expected files: info.txt (num_rows num_cols nnz),
    row_ptr.txt, col_idx.txt, data.txt (one value per line).

    Returns: (row_ptr, col_idx, data, num_rows, num_cols, nnz)
    """
    with open(os.path.join(dirpath, "info.txt")) as f:
        parts = f.read().strip().split()
        num_rows, num_cols, nnz = int(parts[0]), int(parts[1]), int(parts[2])
    with open(os.path.join(dirpath, "row_ptr.txt")) as f:
        row_ptr = [int(line.strip()) for line in f if line.strip()]
    with open(os.path.join(dirpath, "col_idx.txt")) as f:
        col_idx = [int(line.strip()) for line in f if line.strip()]
    with open(os.path.join(dirpath, "data.txt")) as f:
        data = [float(line.strip()) for line in f if line.strip()]
    return (row_ptr, col_idx, data, num_rows, num_cols, nnz)


def csr_to_jds(row_ptr, col_idx, data, num_rows):
    """Convert CSR to Jagged Diagonal Storage format.

    Returns: (row_perm, row_nnz, col_start, jds_col_idx, jds_data)
    """
    nnz_per_row = [row_ptr[i + 1] - row_ptr[i] for i in range(num_rows)]

    # Sort rows by non-zero count for JDS layout
    indices = list(range(num_rows))
    indices.sort(key=lambda i: (nnz_per_row[i], i))

    row_perm = indices
    row_nnz = [nnz_per_row[i] for i in indices]

    max_row_nnz = max(row_nnz) if row_nnz else 0
    if max_row_nnz == 0:
        return (row_perm, row_nnz, [], [], [])

    # Compute jagged diagonal start offsets
    col_start = [0]
    for col in range(max_row_nnz - 1):
        count = sum(1 for nnz in row_nnz if nnz > col)
        col_start.append(col_start[-1] + count)

    # Place entries into JDS arrays
    total_nnz = row_ptr[num_rows]
    jds_col_idx = [0] * total_nnz
    jds_data = [0.0] * total_nnz

    for idx, row in enumerate(row_perm):
        row_nnz_count = nnz_per_row[row]
        for nnz_idx in range(row_nnz_count):
            jds_pos = col_start[nnz_idx] + idx
            csr_pos = row_ptr[row] + nnz_idx
            jds_col_idx[jds_pos] = col_idx[csr_pos]
            jds_data[jds_pos] = data[csr_pos]

    return (row_perm, row_nnz, col_start, jds_col_idx, jds_data)


def csr_to_ell(row_ptr, col_idx, data, num_rows):
    """Convert CSR to ELLPACK format.

    Padding uses -1 for column indices and 0.0 for values.

    Returns: (ell_col_idx, ell_data, max_nnz)
    ell_col_idx and ell_data are list-of-lists (num_rows x max_nnz).
    """
    nnz_per_row = [row_ptr[i + 1] - row_ptr[i] for i in range(num_rows)]
    max_nnz = max(nnz_per_row) if nnz_per_row else 0

    ell_col_idx = []
    ell_data = []

    for i in range(num_rows):
        row_start = row_ptr[i]
        row_end = row_ptr[i + 1]
        row_len = row_end - row_start
        cols = list(col_idx[row_start:row_end]) + [-1] * (max_nnz - row_len)
        vals = list(data[row_start:row_end]) + [0.0] * (max_nnz - row_len)
        ell_col_idx.append(cols)
        ell_data.append(vals)

    return (ell_col_idx, ell_data, max_nnz)


def spmv_csr(row_ptr, col_idx, data, vec, num_rows):
    """SpMV using CSR format."""
    result = [0.0] * num_rows
    for i in range(num_rows):
        s = 0.0
        for j in range(row_ptr[i], row_ptr[i + 1]):
            s += data[j] * vec[col_idx[j]]
        result[i] = s
    return result


def spmv_jds(row_perm, row_nnz, col_start, jds_col_idx, jds_data, vec, num_rows):
    """SpMV using JDS format.

    Iterates over jagged diagonals, accumulating partial products.
    """
    result = [0.0] * num_rows
    max_row_nnz = len(col_start)
    if max_row_nnz == 0:
        return result

    for diag in range(max_row_nnz):
        if diag + 1 < max_row_nnz:
            num_active = col_start[diag + 1] - col_start[diag]
        else:
            num_active = len(jds_data) - col_start[diag]

        for idx in range(num_active):
            pos = col_start[diag] + idx
            col = jds_col_idx[pos]
            val = jds_data[pos]
            result[idx] += val * vec[col]

    return result


def spmv_ell(ell_col_idx, ell_data, vec, num_rows, max_nnz):
    """SpMV using ELLPACK format. Skips padding entries (col == -1)."""
    result = [0.0] * num_rows
    for i in range(num_rows):
        s = 0.0
        for j in range(max_nnz):
            col = ell_col_idx[i][j]
            if col >= 0:
                s += ell_data[i][j] * vec[col]
        result[i] = s
    return result


def memory_traffic_bytes(format_name, num_rows, num_cols, nnz, max_nnz_per_row):
    """Estimate total memory traffic in bytes for one SpMV operation.

    Assumes 4-byte integers and 4-byte floats. Counts both loads and stores.
    """
    if format_name == "csr":
        # row_ptr + col_idx + data + vec + output
        return ((num_rows + 1) + nnz + nnz + num_cols + num_rows) * 4
    elif format_name == "jds":
        # row_perm + row_nnz + col_start + col_idx + data + vec + output
        return (3 * num_rows + max_nnz_per_row + 2 * nnz + num_cols) * 4
    elif format_name == "ell":
        # col_idx + data + vec + output
        return (2 * nnz + num_cols + num_rows) * 4
    else:
        raise ValueError(f"Unknown format: {format_name}")


def simulate_warp_workload(row_work_counts, warp_size):
    """Simulate GPU warp scheduling for SpMV workload distribution.

    Each thread processes one row. Threads are grouped into warps.
    Returns efficiency metrics.
    """
    n = len(row_work_counts)
    if n == 0:
        return {
            "warp_steps": 0,
            "total_slots": 0,
            "active_slots": 0,
            "warp_efficiency": 0.0,
        }

    warp_steps = 0
    for start in range(0, n, warp_size):
        end = min(start + warp_size, n)
        warp_work = row_work_counts[start:end]
        warp_steps += sum(warp_work) // len(warp_work)

    total_slots = warp_steps * warp_size
    active_slots = sum(row_work_counts)
    warp_efficiency = active_slots / total_slots if total_slots > 0 else 0.0

    return {
        "warp_steps": warp_steps,
        "total_slots": total_slots,
        "active_slots": active_slots,
        "warp_efficiency": warp_efficiency,
    }
