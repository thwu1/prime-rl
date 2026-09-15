"""
Complete Optimal Brain Quantization implementation.
"""
import numpy as np


def uniform_quantize(x: np.ndarray, num_bits: int, symmetric: bool = True) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if symmetric:
        q_max = 2 ** (num_bits - 1) - 1
        max_val = np.max(np.abs(x))
        if max_val == 0:
            return np.zeros_like(x)
        scale = max_val / q_max
        q = np.clip(np.round(x / scale), -q_max, q_max)
        return q * scale
    else:
        x_min = float(np.min(x))
        x_max = float(np.max(x))
        q_max = 2 ** num_bits - 1
        if x_max == x_min:
            return np.full_like(x, x_min, dtype=np.float64)
        scale = (x_max - x_min) / q_max
        zero_point = np.clip(np.round(-x_min / scale), 0, q_max)
        q = np.clip(np.round(x / scale + zero_point), 0, q_max)
        return (q - zero_point) * scale


def compute_hessian(X: np.ndarray) -> np.ndarray:
    X = np.asarray(X, dtype=np.float64)
    N = X.shape[0]
    return 2.0 * (X.T @ X) / N


def obq_quantize(W: np.ndarray, H: np.ndarray, num_bits: int,
                  block_size: int = 1, damping: float = 0.01) -> tuple:
    W_orig = W.copy().astype(np.float64)
    W = W.copy().astype(np.float64)
    d_row, d_col = W.shape

    # Regularise and invert
    damp = damping * np.mean(np.diag(H))
    H_damped = H.astype(np.float64) + damp * np.eye(d_col, dtype=np.float64)
    H_inv = np.linalg.inv(H_damped)

    Q = np.zeros_like(W)
    num_blocks = (d_col + block_size - 1) // block_size

    for b in range(num_blocks):
        b_start = b * block_size
        b_end = min(b_start + block_size, d_col)
        bs = b_end - b_start

        H_inv_block = H_inv[b_start:b_end, b_start:b_end]
        err_block = np.zeros((d_row, bs), dtype=np.float64)

        for j in range(bs):
            col_idx = b_start + j
            w_col = W[:, col_idx].copy()
            q_val = uniform_quantize(w_col, num_bits, symmetric=True)
            Q[:, col_idx] = q_val

            err = (w_col - q_val) / H_inv_block[j, j]
            err_block[:, j] = err

            # Within-block compensation
            if j + 1 < bs:
                W[:, col_idx + 1:b_end] -= np.outer(err, H_inv_block[j, j + 1:])

        # Cross-block compensation
        if b_end < d_col:
            W[:, b_end:] -= err_block @ H_inv[b_start:b_end, b_end:]

    diff = W_orig - Q
    hw_error = float(np.trace(diff @ H.astype(np.float64) @ diff.T))
    return Q, hw_error


def obq_quantize_actorder(W: np.ndarray, H: np.ndarray, num_bits: int,
                           block_size: int = 1, damping: float = 0.01) -> tuple:
    H = np.asarray(H, dtype=np.float64)
    W = np.asarray(W, dtype=np.float64)

    perm = np.argsort(np.diag(H))[::-1]
    inv_perm = np.argsort(perm)

    W_perm = W[:, perm].copy()
    H_perm = H[np.ix_(perm, perm)].copy()

    Q_perm, _ = obq_quantize(W_perm, H_perm, num_bits, block_size, damping)
    Q = Q_perm[:, inv_perm]

    diff = W - Q
    hw_error = float(np.trace(diff @ H @ diff.T))
    return Q, hw_error, perm


def mixed_precision_search(layer_sizes: list, error_table: dict,
                            bit_options: list, total_bit_budget: int) -> list:
    K = len(layer_sizes)
    if K == 0:
        return []

    # DP: dp[budget_used] = (total_error, assignment_list)
    dp_prev = {}
    for b in bit_options:
        cost = layer_sizes[0][0] * layer_sizes[0][1] * b
        if (0, b) in error_table and cost <= total_bit_budget:
            err = error_table[(0, b)]
            if cost not in dp_prev or err < dp_prev[cost][0]:
                dp_prev[cost] = (err, [b])

    for k in range(1, K):
        dp_curr = {}
        for prev_cost, (prev_err, prev_assign) in dp_prev.items():
            for b in bit_options:
                if (k, b) not in error_table:
                    continue
                c = layer_sizes[k][0] * layer_sizes[k][1] * b
                new_cost = prev_cost + c
                if new_cost <= total_bit_budget:
                    new_err = prev_err + error_table[(k, b)]
                    if new_cost not in dp_curr or new_err < dp_curr[new_cost][0]:
                        dp_curr[new_cost] = (new_err, prev_assign + [b])
        dp_prev = dp_curr

    if not dp_prev:
        raise ValueError("No feasible bit-width assignment within the budget")

    best_key = min(dp_prev, key=lambda x: dp_prev[x][0])
    return dp_prev[best_key][1]
