"""
NF4 Quantization Engine with Double Quantization.

Pure-Python implementation of a blockwise NormalFloat4 quantization system
with double quantization of scaling constants and memory footprint computation.
"""

import math


def _norm_ppf(p):
    """Compute the inverse CDF (quantile function) of the standard normal N(0,1).

    Uses Peter Acklam's rational approximation with max relative error ~1.15e-9.
    """
    if p <= 0.0:
        return float('-inf')
    if p >= 1.0:
        return float('inf')
    if p == 0.5:
        return 0.0

    a = [
        -3.969683028665376e+01,  2.209460984245205e+02,
        -2.759285104469687e+02,  1.383577518672690e+02,
        -3.066479806614716e+01,  2.506628277459239e+00,
    ]
    b = [
        -5.447609879822406e+01,  1.615858368580409e+02,
        -1.556989798598866e+02,  6.680131188771972e+01,
        -1.328068155288572e+01,
    ]
    c = [
        -7.784894002430293e-03, -3.223964580411365e-01,
        -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00,  2.938163982698783e+00,
    ]
    d = [
         7.784695709041462e-03,  3.224671290700398e-01,
         2.445134137142996e+00,  3.754408661907416e+00,
    ]

    p_low = 0.02425
    p_high = 1.0 - p_low

    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
            ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1.0)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        x = (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5]) * q / \
            (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1.0)
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
             ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1.0)

    return x


def _linspace(start, stop, num):
    """Return num evenly spaced floats from start to stop (inclusive)."""
    if num == 1:
        return [start]
    step = (stop - start) / (num - 1)
    return [start + i * step for i in range(num)]


def create_nf4_map():
    """Create the 16-value NF4 (NormalFloat4) quantization map.

    Derives values from quantiles of N(0,1) with asymmetric scheme:
    8 negative quantile values, zero, and 7 positive quantile values + boundary
    (yielding 15 non-zero values total).

    Returns:
        list of 16 sorted floats in [-1, 1].
    """
    offset = 0.9

    # Negative side: 9 quantile points from offset to 0.5, take first 8
    neg_quantile_pts = _linspace(offset, 0.5, 9)
    v_neg = [_norm_ppf(p) for p in neg_quantile_pts[:8]]

    # Positive side: 8 quantile points from offset to 0.5, take first 7
    pos_quantile_pts = _linspace(offset, 0.5, 8)
    v_pos = [-_norm_ppf(p) for p in pos_quantile_pts[:7]]

    values = v_neg + [0.0] + v_pos
    values.sort()

    max_abs = max(abs(v) for v in values)
    values = [v / max_abs for v in values]

    return values


def quantize_blockwise_nf4(data, blocksize):
    """Blockwise 4-bit NF4 quantization.

    Args:
        data: list of floats to quantize.
        blocksize: number of elements per block.

    Returns:
        dict with keys: indices, absmax, blocksize, num_elements.
    """
    nf4_map = create_nf4_map()
    n = len(data)
    indices = []
    absmax_list = []

    for block_start in range(0, n, blocksize):
        block_end = min(block_start + blocksize, n)
        block = data[block_start:block_end]

        am = max(block) if block else 0.0
        absmax_list.append(am)

        for val in block:
            if am == 0.0:
                best_idx = 0
                best_dist = abs(nf4_map[0])
                for j, nf4_val in enumerate(nf4_map):
                    if abs(nf4_val) < best_dist:
                        best_dist = abs(nf4_val)
                        best_idx = j
                indices.append(best_idx)
            else:
                normalized = val / am
                best_idx = 0
                best_dist = abs(normalized - nf4_map[0])
                for j in range(1, 16):
                    dist = abs(normalized - nf4_map[j])
                    if dist < best_dist:
                        best_dist = dist
                        best_idx = j
                indices.append(best_idx)

    return {
        "indices": indices,
        "absmax": absmax_list,
        "blocksize": blocksize,
        "num_elements": n,
    }


def dequantize_blockwise_nf4(qstate):
    """Blockwise 4-bit NF4 dequantization.

    Args:
        qstate: dict from quantize_blockwise_nf4.

    Returns:
        list of floats (reconstructed values).
    """
    nf4_map = create_nf4_map()
    indices = qstate["indices"]
    absmax_list = qstate["absmax"]
    blocksize = qstate["blocksize"]
    n = qstate["num_elements"]

    result = []
    for i in range(n):
        block_idx = i // blocksize
        am = absmax_list[block_idx]
        nf4_val = nf4_map[indices[i]]
        result.append(nf4_val * am)

    return result


def double_quantize(absmax_values, inner_blocksize):
    """Quantize FP32 absmax scaling constants to 8-bit.

    Applies blockwise 8-bit linear quantization with blocks of inner_blocksize.

    Args:
        absmax_values: list of FP32 absmax values.
        inner_blocksize: block size for the second-level quantization.

    Returns:
        dict with keys: quantized_absmax, inner_absmax, offset, inner_blocksize.
    """
    n = len(absmax_values)
    offset = sum(absmax_values) / n

    quantized = []
    inner_absmax_list = []

    for block_start in range(0, n, inner_blocksize):
        block_end = min(block_start + inner_blocksize, n)
        block = absmax_values[block_start:block_end]

        am = max(abs(v) for v in block) if block else 0.0
        inner_absmax_list.append(am)

        for val in block:
            if am == 0.0:
                quantized.append(0)
            else:
                q = round(127.0 * val / am)
                q = max(-127, min(127, q))
                quantized.append(q)

    return {
        "quantized_absmax": quantized,
        "inner_absmax": inner_absmax_list,
        "offset": offset,
        "inner_blocksize": inner_blocksize,
    }


def double_dequantize(dq_state):
    """Recover FP32 absmax values from double-quantized state.

    Args:
        dq_state: dict from double_quantize.

    Returns:
        list of FP32 absmax values.
    """
    quantized = dq_state["quantized_absmax"]
    inner_absmax_list = dq_state["inner_absmax"]
    offset = dq_state["offset"]
    inner_blocksize = dq_state["inner_blocksize"]

    result = []
    for i, q in enumerate(quantized):
        block_idx = i // inner_blocksize
        am = inner_absmax_list[block_idx]
        val = (q * am / 127.0) + offset
        result.append(val)

    return result


def compute_memory_bits_per_param(blocksize, double_quant, inner_blocksize=256):
    """Compute average bits per parameter for NF4 quantization.

    Without double quantization:
        bits_per_param = 4 + 32 / blocksize

    With double quantization:
        bits_per_param = 4 + 8 / blocksize + 32 / (blocksize * inner_blocksize)

    Args:
        blocksize: outer block size for 4-bit weight quantization.
        double_quant: whether double quantization is applied.
        inner_blocksize: block size for second-level quantization of absmax values.

    Returns:
        float: average bits per parameter.
    """
    weight_bits = 4.0

    if double_quant:
        absmax_bits = 8.0 / blocksize + 32.0 / (blocksize * inner_blocksize)
    else:
        absmax_bits = 32.0 / blocksize

    return weight_bits + absmax_bits
