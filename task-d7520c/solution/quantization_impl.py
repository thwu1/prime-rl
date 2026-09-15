"""
NF4 Quantization Implementation — Solution

Implements the NormalFloat4 (NF4) data type and block-wise quantization
as described in "QLoRA: Efficient Finetuning of Quantized LLMs".
"""

import torch
import numpy as np
from scipy.stats import norm
from typing import Dict, Tuple


def create_nf4_map(offset: float = 0.9677083) -> torch.Tensor:
    """Construct the NF4 quantization map using N(0,1) quantiles."""
    # Positive side: 8 values from norm.ppf at evenly spaced quantiles
    pos_quantiles = np.linspace(offset, 0.5, 9)[:-1]
    v_pos = norm.ppf(pos_quantiles).tolist()

    # Negative side: 7 values (negated ppf values at different spacing)
    neg_quantiles = np.linspace(offset, 0.5, 8)[:-1]
    v_neg = (-norm.ppf(neg_quantiles)).tolist()

    # Zero padding for 256-element tensor (8-bit indexing)
    v_pad = [0.0] * (256 - 15)

    values = torch.tensor(v_pos + v_pad + v_neg, dtype=torch.float32)
    values = values.sort().values
    values /= values.max()

    return values


def _find_nearest_level(values: torch.Tensor, levels: torch.Tensor) -> torch.Tensor:
    """Find the index of the nearest level for each value using binary search."""
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
    """Quantize a tensor to 4-bit NF4 using block-wise absmax scaling."""
    nf4_map = create_nf4_map()
    levels = torch.unique(nf4_map)  # 16 sorted unique values

    original_shape = tensor.shape
    flat = tensor.float().reshape(-1)
    n = flat.numel()

    # Pad to multiple of blocksize
    pad_size = (blocksize - n % blocksize) % blocksize
    if pad_size > 0:
        flat = torch.cat([flat, torch.zeros(pad_size)])

    # Block-wise quantization
    blocks = flat.reshape(-1, blocksize)
    absmax = blocks.abs().max(dim=1).values.clamp(min=1e-10)
    normalized = blocks / absmax.unsqueeze(1)

    # Find nearest NF4 level for each normalized value
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
    """Dequantize NF4 tensor back to float32."""
    levels = quant_state["levels"]
    absmax = quant_state["absmax"]
    blocksize = quant_state["blocksize"]
    original_shape = quant_state["shape"]
    n = quant_state["numel"]

    # Look up NF4 levels from indices
    dequantized = levels[quantized.long()]

    # Reshape into blocks and scale by absmax
    blocks = dequantized.reshape(-1, blocksize)
    blocks = blocks * absmax.unsqueeze(1)

    # Flatten and trim padding
    flat = blocks.reshape(-1)[:n]

    return flat.reshape(original_shape)


def double_quantize(
    absmax: torch.Tensor,
    blocksize: int = 256,
) -> Tuple[torch.Tensor, Dict]:
    """Double-quantize absmax values: mean-center then 8-bit block-wise."""
    # Mean-center to make values suitable for symmetric quantization
    offset = absmax.mean()
    centered = absmax - offset

    n = centered.numel()

    # Pad to multiple of blocksize
    pad_size = (blocksize - n % blocksize) % blocksize
    if pad_size > 0:
        centered = torch.cat([centered, torch.zeros(pad_size)])

    # Block-wise 8-bit linear quantization
    blocks = centered.reshape(-1, blocksize)
    absmax2 = blocks.abs().max(dim=1).values.clamp(min=1e-10)
    normalized = blocks / absmax2.unsqueeze(1)

    # Map [-1, 1] to [0, 255]
    quantized = torch.clamp(torch.round((normalized + 1.0) * 127.5), 0, 255).byte()

    dq_state = {
        "absmax2": absmax2,
        "offset": offset,
        "blocksize": blocksize,
        "numel": n,
    }

    return quantized.reshape(-1), dq_state


def double_dequantize(
    quantized_absmax: torch.Tensor,
    dq_state: Dict,
) -> torch.Tensor:
    """Recover absmax values from double quantization."""
    absmax2 = dq_state["absmax2"]
    offset = dq_state["offset"]
    blocksize = dq_state["blocksize"]
    n = dq_state["numel"]

    # Reverse the 8-bit linear quantization
    values = quantized_absmax.float() / 127.5 - 1.0

    # Reshape into blocks and scale by second-level absmax
    blocks = values.reshape(-1, blocksize)
    blocks = blocks * absmax2.unsqueeze(1)

    # Trim padding and add back the mean offset
    flat = blocks.reshape(-1)[:n]

    return flat + offset
