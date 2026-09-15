"""Block-wise 4-bit model weight quantization with optional nested statistics compression."""


import numpy as np


def create_nf4_map(offset=0.9677083):
    """Create the 16-level NF4 quantization map, normalized to [-1, 1]."""
    from scipy.stats import norm

    # Positive side: ppf at 8 evenly spaced quantile boundary points
    pos_quantiles = np.linspace(offset, 0.5, 9)[:-1]
    v_pos = norm.ppf(pos_quantiles).tolist()

    # Negative side: ppf at 7 evenly spaced quantile boundary points, negated
    neg_quantiles = np.linspace(offset, 0.5, 8)[:-1]
    v_neg = (-norm.ppf(neg_quantiles)).tolist()

    values = v_neg + [0.0] + v_pos
    values = np.array(sorted(values), dtype=np.float64)
    values /= np.abs(values).max()
    return values.astype(np.float32)


def create_dynamic_map(signed=True, max_exponent_bits=7, total_bits=8):
    """Create the 256-level dynamic quantization map for 8-bit block-wise quantization."""
    data = []
    non_sign_bits = total_bits - 1
    additional_items = 2 ** (non_sign_bits - max_exponent_bits) - 1

    last_i = 0
    for i in range(max_exponent_bits):
        last_i = i
        if signed:
            fraction_items = int(2 ** (i + non_sign_bits - max_exponent_bits) + 1)
        else:
            fraction_items = int(2 ** (i + non_sign_bits - max_exponent_bits + 1) + 1)

        boundaries = np.linspace(0.1, 1.0, fraction_items, dtype=np.float64)
        means = (boundaries[:-1] + boundaries[1:]) / 2.0
        scale = 10.0 ** (-(max_exponent_bits - 1) + i)
        data += (scale * means).tolist()
        if signed:
            data += (-scale * means).tolist()

    if additional_items > 0:
        boundaries = np.linspace(0.1, 1.0, additional_items + 1, dtype=np.float64)
        means = (boundaries[:-1] + boundaries[1:]) / 2.0
        scale = 10.0 ** (-(max_exponent_bits - 1) + last_i)
        data += (scale * means).tolist()
        if signed:
            data += (-scale * means).tolist()

    data.append(0.0)
    data.append(1.0)

    gap = 256 - len(data)
    data += [0.0] * gap

    data.sort()
    return np.array(data, dtype=np.float32)


def pack_4bit(indices):
    """Pack an array of 4-bit indices into uint8 bytes, two indices per byte."""
    indices = np.asarray(indices, dtype=np.uint8)
    n = len(indices)
    if n % 2 != 0:
        indices = np.concatenate([indices, np.zeros(1, dtype=np.uint8)])

    even = indices[0::2]
    odd = indices[1::2]
    packed = ((odd.astype(np.uint16) << 4) | even.astype(np.uint16)).astype(np.uint8)
    return packed


def unpack_4bit(packed, count=None):
    """Unpack uint8 bytes back to 4-bit indices."""
    packed = np.asarray(packed, dtype=np.uint8)
    low = packed & 0x0F
    high = (packed >> 4) & 0x0F
    result = np.empty(len(packed) * 2, dtype=np.uint8)
    result[0::2] = low
    result[1::2] = high
    if count is not None:
        result = result[:count]
    return result


def quantize_nf4(tensor, blocksize=64, compress_statistics=False, dq_blocksize=256):
    """Quantize a float tensor using block-wise NF4 quantization."""
    tensor = np.asarray(tensor)
    original_shape = tensor.shape
    quant_map = create_nf4_map()

    flat = tensor.astype(np.float32).flatten()
    n = flat.size

    pad_size = (blocksize - n % blocksize) % blocksize
    if pad_size > 0:
        flat = np.concatenate([flat, np.zeros(pad_size, dtype=np.float32)])

    total = flat.size
    num_blocks = total // blocksize
    blocks = flat.reshape(num_blocks, blocksize)

    absmax = np.abs(blocks).max(axis=1).astype(np.float32)
    safe_absmax = np.maximum(absmax, 1e-12)

    normalized = blocks / safe_absmax[:, np.newaxis]

    flat_norm = normalized.flatten()
    diffs = np.abs(flat_norm[:, np.newaxis] - quant_map[np.newaxis, :])
    indices = np.argmin(diffs, axis=1).astype(np.uint8)

    packed = pack_4bit(indices)

    quant_state = {
        "packed_data": packed,
        "absmax": absmax,
        "quant_map": quant_map,
        "original_shape": original_shape,
        "blocksize": blocksize,
        "total_elements": total,
        "compress_statistics": compress_statistics,
    }

    if compress_statistics:
        dq_map = create_dynamic_map(signed=True)
        offset = np.float32(absmax.mean())
        centered = absmax - offset

        n_absmax = centered.size
        dq_pad = (dq_blocksize - n_absmax % dq_blocksize) % dq_blocksize
        if dq_pad > 0:
            centered_padded = np.concatenate(
                [centered, np.zeros(dq_pad, dtype=np.float32)]
            )
        else:
            centered_padded = centered.copy()

        n_dq_blocks = centered_padded.size // dq_blocksize
        dq_blocks = centered_padded.reshape(n_dq_blocks, dq_blocksize)
        nested_absmax = np.abs(dq_blocks).max(axis=1).astype(np.float32)
        safe_nested = np.maximum(nested_absmax, 1e-12)

        dq_normalized = dq_blocks / safe_nested[:, np.newaxis]
        dq_flat = dq_normalized.flatten()

        dq_diffs = np.abs(dq_flat[:, np.newaxis] - dq_map[np.newaxis, :])
        dq_indices = np.argmin(dq_diffs, axis=1).astype(np.uint8)

        if dq_pad > 0:
            dq_indices = dq_indices[:n_absmax]

        quant_state["absmax"] = dq_indices
        quant_state["nested_absmax"] = nested_absmax
        quant_state["nested_quant_map"] = dq_map
        quant_state["offset"] = offset
        quant_state["dq_blocksize"] = dq_blocksize
        quant_state["num_absmax"] = n_absmax

    return quant_state


def dequantize_nf4(quant_state):
    """Dequantize an NF4 quant_state back to float32."""
    packed = quant_state["packed_data"]
    quant_map = quant_state["quant_map"]
    original_shape = quant_state["original_shape"]
    blocksize = quant_state["blocksize"]
    total = quant_state["total_elements"]
    compress = quant_state["compress_statistics"]

    indices = unpack_4bit(packed, count=total)

    if compress:
        dq_indices = quant_state["absmax"]
        nested_absmax = quant_state["nested_absmax"]
        dq_map = quant_state["nested_quant_map"]
        offset = quant_state["offset"]
        dq_blocksize = quant_state["dq_blocksize"]
        n_absmax = quant_state["num_absmax"]

        dq_pad = (dq_blocksize - n_absmax % dq_blocksize) % dq_blocksize
        if dq_pad > 0:
            dq_indices_padded = np.concatenate(
                [dq_indices, np.zeros(dq_pad, dtype=np.uint8)]
            )
        else:
            dq_indices_padded = dq_indices

        dq_values = dq_map[dq_indices_padded]
        n_dq_blocks = dq_values.size // dq_blocksize
        dq_values = dq_values.reshape(n_dq_blocks, dq_blocksize)
        dq_values = dq_values * nested_absmax[:, np.newaxis]
        dq_values = dq_values.flatten()[:n_absmax]

        absmax = dq_values + offset
    else:
        absmax = quant_state["absmax"]

    values = quant_map[indices]
    num_blocks = total // blocksize
    values = values.reshape(num_blocks, blocksize)
    values = values * absmax[:num_blocks, np.newaxis]
    values = values.flatten()

    n = int(np.prod(original_shape))
    values = values[:n]
    return values.reshape(original_shape).astype(np.float32)


def compute_memory_bytes(num_params, blocksize=64, double_quant=False, dq_blocksize=256):
    """Compute the exact memory footprint in bytes for NF4-quantized parameters."""
    weight_bytes = (num_params + 1) // 2

    num_blocks = (num_params + blocksize - 1) // blocksize

    if not double_quant:
        absmax_bytes = num_blocks * 4
    else:
        absmax_bytes = num_blocks
        nested_blocks = (num_blocks + dq_blocksize - 1) // dq_blocksize
        absmax_bytes += nested_blocks * 4

    return weight_bytes + absmax_bytes
