"""
NF4 Quantization — 4-bit NormalFloat data type and block-wise quantization.
"""

import torch
from typing import Dict, Tuple


def create_nf4_map(offset: float = 0.9677083) -> torch.Tensor:
    """Construct the NF4 quantization map using quantiles of N(0,1).

    Creates a 256-element tensor containing unique quantization levels
    normalized to [-1, 1], with zero-padding for 8-bit indexing.

    Args:
        offset: The outermost quantile boundary controlling tail coverage.

    Returns:
        A 256-element float32 tensor of sorted quantization levels.
    """
    from scipy.stats import norm
    import numpy as np

    # Compute positive and negative quantization levels from normal quantiles
    v_pos = norm.ppf(np.linspace(offset, 0.5, 8)[:-1]).tolist()
    v_neg = (-norm.ppf(np.linspace(offset, 0.5, 8)[:-1])).tolist()

    v_pad = [0.0] * (256 - 14)

    values = torch.tensor(v_pos + v_pad + v_neg, dtype=torch.float32)
    values = values.sort().values
    values /= values.max()

    return values


def _find_nearest_level(values: torch.Tensor, levels: torch.Tensor) -> torch.Tensor:
    """Map each value to the index of its nearest quantization level."""
    idx = torch.searchsorted(levels.contiguous(), values.contiguous())
    idx = idx.clamp(0, len(levels) - 1)
    left_idx = (idx - 1).clamp(min=0)

    dist_right = (values - levels[idx]).abs()
    dist_left = (values - levels[left_idx]).abs()

    return torch.where(dist_left < dist_right, left_idx, idx)


def quantize_nf4(
    tensor: torch.Tensor,
    blocksize: int = 64,
) -> Tuple[torch.Tensor, Dict]:
    """Quantize a float32 tensor to 4-bit NF4 using block-wise absmax scaling.

    Args:
        tensor: Input tensor (any shape, float32).
        blocksize: Number of elements per quantization block.

    Returns:
        Tuple of (quantized uint8 tensor, quantization state dict).
    """
    nf4_map = create_nf4_map()
    levels = torch.unique(nf4_map)

    original_shape = tensor.shape
    flat = tensor.float().reshape(-1)
    n = flat.numel()

    pad_size = (blocksize - n % blocksize) % blocksize
    if pad_size > 0:
        flat = torch.cat([flat, torch.zeros(pad_size)])

    blocks = flat.reshape(-1, blocksize)
    absmax = blocks.abs().max(dim=1).values.clamp(min=1e-10)
    normalized = blocks / absmax.unsqueeze(1)

    flat_norm = normalized.reshape(-1)
    indices = _find_nearest_level(flat_norm, levels)

    quant_state = {
        "absmax": absmax,
        "shape": original_shape,
        "blocksize": blocksize,
        "nf4_map": nf4_map,
        "levels": levels,
        "numel": n,
    }

    return indices.byte(), quant_state


def dequantize_nf4(
    quantized: torch.Tensor,
    quant_state: Dict,
) -> torch.Tensor:
    """Dequantize NF4 tensor back to float32.

    Args:
        quantized: uint8 tensor of NF4 indices.
        quant_state: State dict from quantize_nf4.

    Returns:
        Reconstructed float32 tensor with original shape.
    """
    levels = quant_state["levels"]
    absmax = quant_state["absmax"]
    blocksize = quant_state["blocksize"]
    original_shape = quant_state["shape"]
    n = quant_state["numel"]

    dequantized = levels[quantized.long()]
    blocks = dequantized.reshape(-1, blocksize)
    blocks = blocks * absmax.unsqueeze(1)
    flat = blocks.reshape(-1)[:n]

    return flat.reshape(original_shape)


def double_quantize(
    absmax: torch.Tensor,
    blocksize: int = 256,
) -> Tuple[torch.Tensor, Dict]:
    """Compress absmax scaling factors using 8-bit block-wise quantization.

    Args:
        absmax: Float32 tensor of per-block scaling factors.
        blocksize: Block size for secondary quantization.

    Returns:
        Tuple of (uint8 quantized absmax, secondary quantization state dict).
    """
    n = absmax.numel()

    centered = absmax.clone()

    pad_size = (blocksize - n % blocksize) % blocksize
    if pad_size > 0:
        centered = torch.cat([centered, torch.zeros(pad_size)])

    blocks = centered.reshape(-1, blocksize)
    absmax2 = blocks.abs().max(dim=1).values.clamp(min=1e-10)
    normalized = blocks / absmax2.unsqueeze(1)

    quantized = torch.clamp(torch.round((normalized + 1.0) * 127.5), 0, 255).byte()

    dq_state = {
        "absmax2": absmax2,
        "offset": torch.tensor(0.0),
        "blocksize": blocksize,
        "numel": n,
    }

    return quantized.reshape(-1), dq_state


def double_dequantize(
    quantized_absmax: torch.Tensor,
    dq_state: Dict,
) -> torch.Tensor:
    """Recover absmax values from secondary quantization.

    Args:
        quantized_absmax: uint8 tensor from double_quantize.
        dq_state: State dict from double_quantize.

    Returns:
        Recovered float32 absmax tensor.
    """
    absmax2 = dq_state["absmax2"]
    offset = dq_state["offset"]
    blocksize = dq_state["blocksize"]
    n = dq_state["numel"]

    values = quantized_absmax.float() / 127.5 - 1.0
    blocks = values.reshape(-1, blocksize)
    blocks = blocks * absmax2.unsqueeze(1)
    flat = blocks.reshape(-1)[:n]

    return flat + offset
