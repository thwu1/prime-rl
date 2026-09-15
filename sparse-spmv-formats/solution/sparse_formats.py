#!/usr/bin/env python3
"""
Sparse Matrix Multi-Format SpMV Analyzer.

Implements CSR, JDS (Jagged Diagonal Storage), and ELLPACK formats
with SpMV computation, GPU memory traffic estimation, and warp-level
workload simulation.
"""


def csr_to_jds(row_ptr, col_idx, data, num_rows):
    """Convert CSR to Jagged Diagonal Storage (JDS) format.

    Rows are sorted by non-zero count descending, with ties broken by
    ascending original row index (stable).

    Returns:
        (row_perm, row_nnz, col_start, jds_col_idx, jds_data)
        All Python lists.
    """
    # Compute NNZ per row
    nnz_per_row = [row_ptr[i + 1] - row_ptr[i] for i in range(num_rows)]

    # Sort rows by NNZ descending, ties by row index ascending
    indices = list(range(num_rows))
    indices.sort(key=lambda i: (-nnz_per_row[i], i))

    row_perm = indices
    row_nnz = [nnz_per_row[i] for i in indices]

    # Handle all-empty matrix
    if not row_nnz or row_nnz[0] == 0:
        return (row_perm, row_nnz, [], [], [])

    max_row_nnz = row_nnz[0]

    # Compute column start indices (jagged diagonal offsets)
    # col_start[k] = starting position of the k-th jagged diagonal
    col_start = [0]
    for col in range(max_row_nnz - 1):
        count = 0
        for nnz in row_nnz:
            if nnz > col:
                count += 1
        col_start.append(col_start[-1] + count)

    # Build JDS data and column index arrays
    total_nnz = row_ptr[num_rows]
    jds_col_idx = [0] * total_nnz
    jds_data = [0.0] * total_nnz

    for idx, row in enumerate(row_perm):
        row_nnz_count = row_nnz[idx]
        for nnz_idx in range(row_nnz_count):
            jds_pos = col_start[nnz_idx] + idx
            csr_pos = row_ptr[row] + nnz_idx
            jds_col_idx[jds_pos] = col_idx[csr_pos]
            jds_data[jds_pos] = data[csr_pos]

    return (row_perm, row_nnz, col_start, jds_col_idx, jds_data)


def csr_to_ell(row_ptr, col_idx, data, num_rows):
    """Convert CSR to ELLPACK format.

    Every row is padded to max_nnz_per_row width.
    Padding uses -1 for column indices and 0.0 for values.

    Returns:
        (ell_col_idx, ell_data, max_nnz)
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
    """Sparse matrix-vector multiplication using CSR format."""
    result = [0.0] * num_rows
    for i in range(num_rows):
        s = 0.0
        for j in range(row_ptr[i], row_ptr[i + 1]):
            s += data[j] * vec[col_idx[j]]
        result[i] = s
    return result


def spmv_jds(row_perm, row_nnz, col_start, jds_col_idx, jds_data, vec, num_rows):
    """Sparse matrix-vector multiplication using JDS format.

    Iterates over jagged diagonals and scatters results back to
    original row positions via row_perm.
    """
    result = [0.0] * num_rows

    max_row_nnz = len(col_start)
    if max_row_nnz == 0:
        return result

    for diag in range(max_row_nnz):
        # Number of rows participating in this diagonal
        if diag + 1 < max_row_nnz:
            num_active = col_start[diag + 1] - col_start[diag]
        else:
            num_active = len(jds_data) - col_start[diag]

        for idx in range(num_active):
            pos = col_start[diag] + idx
            col = jds_col_idx[pos]
            val = jds_data[pos]
            row = row_perm[idx]
            result[row] += val * vec[col]

    return result


def spmv_ell(ell_col_idx, ell_data, vec, num_rows, max_nnz):
    """Sparse matrix-vector multiplication using ELLPACK format."""
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
    """Compute total memory traffic in bytes for one SpMV operation.

    Assumes 4-byte floats and 4-byte integers.
    """
    if format_name == "csr":
        # row_ptr: (num_rows+1) ints, col_idx: nnz ints, data: nnz floats
        # vec: num_cols floats, output: num_rows floats
        return ((num_rows + 1) + nnz + nnz + num_cols + num_rows) * 4

    elif format_name == "jds":
        # row_perm: num_rows ints, row_nnz: num_rows ints
        # col_start: max_nnz_per_row ints
        # jds_col_idx: nnz ints, jds_data: nnz floats
        # vec: num_cols floats, output: num_rows floats
        return (3 * num_rows + max_nnz_per_row + 2 * nnz + num_cols) * 4

    elif format_name == "ell":
        # ell_col_idx: num_rows*max_nnz ints, ell_data: num_rows*max_nnz floats
        # vec: num_cols floats, output: num_rows floats
        return (2 * num_rows * max_nnz_per_row + num_cols + num_rows) * 4

    else:
        raise ValueError(f"Unknown format: {format_name}")


def simulate_warp_workload(row_work_counts, warp_size):
    """Simulate GPU warp-level workload distribution for SpMV.

    Thread t is assigned to row t. Threads are grouped into warps of
    warp_size. Each warp executes for max(work_in_warp) steps due to
    SIMT lockstep execution. Partial last warps still occupy warp_size
    thread slots.

    Returns dict with:
        warp_steps: sum of per-warp max work count
        total_slots: warp_steps * warp_size (scheduled thread-iterations)
        active_slots: sum of all row_work_counts (useful thread-iterations)
        warp_efficiency: active_slots / total_slots
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
        warp_max = max(row_work_counts[start:end])
        warp_steps += warp_max

    total_slots = warp_steps * warp_size
    active_slots = sum(row_work_counts)
    warp_efficiency = active_slots / total_slots if total_slots > 0 else 0.0

    return {
        "warp_steps": warp_steps,
        "total_slots": total_slots,
        "active_slots": active_slots,
        "warp_efficiency": warp_efficiency,
    }
