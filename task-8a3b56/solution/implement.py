#!/usr/bin/env python3

"""
Solution: writes the full implementation of quantlib/core.py.
"""


"""
4-bit NormalFloat (NF4) quantization library.

Implements blockwise 4-bit quantization with NF4 and FP4 data types,
double quantization for absmax compression, and memory footprint analysis.
"""

import itertools
import math
from typing import Optional

import torch


class QuantState:
    """Container for quantization state needed to dequantize a tensor."""

    def __init__(
        self,
        absmax: torch.Tensor,
        shape: tuple,
        code: torch.Tensor,
        blocksize: int,
        dtype: torch.dtype,
        quant_type: str,
        offset: Optional[torch.Tensor] = None,
        state2: Optional["QuantState"] = None,
    ):
        self.absmax = absmax
        self.shape = shape
        self.code = code
        self.blocksize = blocksize
        self.dtype = dtype
        self.quant_type = quant_type
        self.offset = offset
        self.state2 = state2

    @property
    def nested(self) -> bool:
        return self.state2 is not None


# ---------------------------------------------------------------------------
# Quantization map construction
# ---------------------------------------------------------------------------

def create_nf4_map(offset: float = 0.9677083) -> torch.Tensor:
    """Create the NormalFloat4 quantization codebook (16 levels)."""
    from scipy.stats import norm

    # Positive side: 8 quantile values from offset down toward 0.5
    # (norm.ppf of values > 0.5 gives positive numbers)
    v_pos = norm.ppf(torch.linspace(offset, 0.5, 9)[:-1]).tolist()  # 8 values

    # Negative side: 7 quantile values, mirrored
    v_neg = (-norm.ppf(torch.linspace(offset, 0.5, 8)[:-1])).tolist()  # 7 values

    # Combine with a single zero
    values = v_neg + [0.0] + v_pos  # 7 + 1 + 8 = 16

    t = torch.tensor(values, dtype=torch.float32)
    t = t.sort().values
    t = t / t.max()  # normalize to [-1, 1]
    return t


def create_fp4_map() -> torch.Tensor:
    """Create the FP4 (4-bit floating point) quantization codebook (16 levels)."""
    signed = True
    exponent_bits = 2
    precision_bits = 1
    total_bits = 4

    bias = 2 ** (exponent_bits - 1)  # 2
    values = []
    mantissa_patterns = list(itertools.product([0, 1], repeat=precision_bits))

    for evalue in range(2 ** exponent_bits):  # 0, 1, 2, 3
        for bits in mantissa_patterns:
            # Build mantissa fraction
            if evalue != 0:
                mantissa_val = 1.0  # implicit leading 1 for normals
            else:
                mantissa_val = 0.0  # no implicit 1 for subnormals

            for i, b in enumerate(bits):
                mantissa_val += b * (2 ** -(i + 1))

            if evalue == 0:
                # Subnormal
                value = mantissa_val * (2 ** (-bias))
            else:
                # Normal
                value = mantissa_val * (2 ** (-(evalue - bias - 1)))

            values.append(value)
            if signed:
                values.append(-value)

    assert len(values) == 2 ** total_bits
    values.sort()

    t = torch.tensor(values, dtype=torch.float32)
    t = t / t.max()
    return t


def create_dynamic_map(signed=True, max_exponent_bits=7, total_bits=8):
    """Create the 256-level dynamic quantization map for 8-bit quantization."""
    data = []
    non_sign_bits = total_bits - 1
    additional_items = 2 ** (non_sign_bits - max_exponent_bits) - 1

    last_i = 0
    for i in range(max_exponent_bits):
        last_i = i
        fraction_items = int(
            2 ** (i + non_sign_bits - max_exponent_bits) + 1
            if signed
            else 2 ** (i + non_sign_bits - max_exponent_bits + 1) + 1,
        )
        boundaries = torch.linspace(0.1, 1, fraction_items, dtype=torch.float32)
        means = (boundaries[:-1] + boundaries[1:]) / 2.0
        data += ((10 ** (-(max_exponent_bits - 1) + i)) * means).tolist()
        if signed:
            data += (-(10 ** (-(max_exponent_bits - 1) + i)) * means).tolist()

    if additional_items > 0:
        boundaries = torch.linspace(
            0.1, 1, additional_items + 1, dtype=torch.float32
        )
        means = (boundaries[:-1] + boundaries[1:]) / 2.0
        data += ((10 ** (-(max_exponent_bits - 1) + last_i)) * means).tolist()
        if signed:
            data += (-(10 ** (-(max_exponent_bits - 1) + last_i)) * means).tolist()

    data.append(0)
    data.append(1.0)

    assert len(data) == 2 ** total_bits

    gap = 256 - len(data)
    for _ in range(gap):
        data.append(0)

    data.sort()
    return torch.tensor(data, dtype=torch.float32)


# ---------------------------------------------------------------------------
# 8-bit blockwise quantize/dequantize (internal, for double quantization)
# ---------------------------------------------------------------------------

def _quantize_blockwise_8bit(tensor, code=None, blocksize=256):
    """8-bit blockwise quantization using the dynamic map."""
    if code is None:
        code = create_dynamic_map()

    A = tensor.float().reshape(-1)
    n = A.numel()

    # Pad to multiple of blocksize
    remainder = n % blocksize
    if remainder != 0:
        pad = blocksize - remainder
        A = torch.cat([A, torch.zeros(pad, dtype=torch.float32)])

    n_blocks = A.numel() // blocksize
    blocks = A.reshape(n_blocks, blocksize)

    # Per-block absmax
    absmax = blocks.abs().max(dim=1).values.float()
    scale = absmax.clone()
    scale[scale == 0] = 1.0

    normalized = blocks / scale.unsqueeze(1)

    # Nearest-neighbor lookup in the 256-element code
    # Process in chunks to avoid OOM on large tensors
    chunk_size = 4096
    all_indices = []
    for start in range(0, normalized.shape[0], chunk_size):
        end = min(start + chunk_size, normalized.shape[0])
        chunk = normalized[start:end]  # (chunk_blocks, blocksize)
        diffs = (chunk.unsqueeze(-1) - code.unsqueeze(0).unsqueeze(0)).abs()
        idx = diffs.argmin(dim=-1).byte()
        all_indices.append(idx)

    indices = torch.cat(all_indices, dim=0)
    indices = indices.reshape(-1)[:n]

    state = QuantState(
        absmax=absmax,
        shape=tensor.shape,
        code=code.clone(),
        blocksize=blocksize,
        dtype=tensor.dtype,
        quant_type="dynamic",
    )
    return indices, state


def _dequantize_blockwise_8bit(quantized, quant_state):
    """Dequantize 8-bit blockwise quantized tensor."""
    code = quant_state.code
    absmax = quant_state.absmax
    blocksize = quant_state.blocksize

    indices = quantized.long()
    n = 1
    for s in quant_state.shape:
        n *= s

    # Pad to multiple of blocksize
    n_padded = ((n + blocksize - 1) // blocksize) * blocksize
    if indices.numel() < n_padded:
        indices = torch.cat(
            [indices, torch.zeros(n_padded - indices.numel(), dtype=torch.long)]
        )

    values = code[indices]
    blocks = values.reshape(-1, blocksize)

    # Scale by absmax
    n_blocks_needed = blocks.shape[0]
    am = absmax[:n_blocks_needed]
    result = blocks * am.unsqueeze(1)

    result = result.reshape(-1)[:n]
    return result.to(quant_state.dtype)


# ---------------------------------------------------------------------------
# 4-bit quantize / dequantize
# ---------------------------------------------------------------------------

def quantize_4bit(
    A: torch.Tensor,
    blocksize: int = 64,
    quant_type: str = "nf4",
    compress_statistics: bool = False,
) -> tuple[torch.Tensor, QuantState]:
    """Quantize tensor to 4-bit with blockwise scaling."""
    if quant_type == "nf4":
        code = create_nf4_map()
    elif quant_type == "fp4":
        code = create_fp4_map()
    else:
        raise ValueError(f"Unknown quant_type: {quant_type}")

    original_shape = A.shape
    original_dtype = A.dtype

    A_flat = A.float().reshape(-1)
    n = A_flat.numel()

    # Pad to multiple of blocksize
    remainder = n % blocksize
    if remainder != 0:
        pad = blocksize - remainder
        A_flat = torch.cat([A_flat, torch.zeros(pad, dtype=torch.float32)])

    n_padded = A_flat.numel()
    n_blocks = n_padded // blocksize
    blocks = A_flat.reshape(n_blocks, blocksize)

    # Per-block absmax
    absmax = blocks.abs().max(dim=1).values.float()
    scale = absmax.clone()
    scale[scale == 0] = 1.0

    normalized = blocks / scale.unsqueeze(1)  # in [-1, 1]

    # Nearest-neighbor lookup in the 16-element codebook
    # code shape: (16,)
    # normalized shape: (n_blocks, blocksize)
    diffs = (normalized.unsqueeze(-1) - code.unsqueeze(0).unsqueeze(0)).abs()
    indices = diffs.argmin(dim=-1)  # (n_blocks, blocksize), values 0-15

    # Flatten indices and truncate to original size
    indices_flat = indices.reshape(-1)[:n]

    # Pad to even length for packing
    if n % 2 != 0:
        indices_flat = torch.cat(
            [indices_flat, torch.zeros(1, dtype=indices_flat.dtype)]
        )

    # Pack two 4-bit values per byte: lower nibble = even indices, upper = odd
    low = indices_flat[0::2].byte()
    high = indices_flat[1::2].byte()
    packed = (low & 0x0F) | ((high & 0x0F) << 4)

    # Build QuantState
    if compress_statistics:
        offset = absmax.mean()
        absmax_shifted = absmax - offset
        q_absmax, state2 = _quantize_blockwise_8bit(
            absmax_shifted, blocksize=256
        )
        state = QuantState(
            absmax=q_absmax,
            shape=original_shape,
            code=code,
            blocksize=blocksize,
            dtype=original_dtype,
            quant_type=quant_type,
            offset=offset,
            state2=state2,
        )
    else:
        state = QuantState(
            absmax=absmax,
            shape=original_shape,
            code=code,
            blocksize=blocksize,
            dtype=original_dtype,
            quant_type=quant_type,
        )

    return packed, state


def dequantize_4bit(
    A: torch.Tensor,
    quant_state: QuantState,
) -> torch.Tensor:
    """Dequantize a 4-bit packed tensor."""
    code = quant_state.code  # 16-element codebook
    blocksize = quant_state.blocksize

    # Unpack two 4-bit indices per byte
    low = (A & 0x0F).long()
    high = ((A >> 4) & 0x0F).long()

    n = 1
    for s in quant_state.shape:
        n *= s

    # Interleave low and high
    unpacked = torch.zeros(A.numel() * 2, dtype=torch.long)
    unpacked[0::2] = low
    unpacked[1::2] = high
    unpacked = unpacked[:n]

    # Look up codebook values
    values = code[unpacked]  # float32

    # Recover absmax
    if quant_state.nested:
        absmax = _dequantize_blockwise_8bit(quant_state.absmax, quant_state.state2)
        absmax = absmax + quant_state.offset
        absmax = absmax.float()
    else:
        absmax = quant_state.absmax.float()

    # Pad values to multiple of blocksize for reshaping
    n_padded = ((n + blocksize - 1) // blocksize) * blocksize
    if n < n_padded:
        values = torch.cat(
            [values, torch.zeros(n_padded - n, dtype=torch.float32)]
        )

    blocks = values.reshape(-1, blocksize)
    n_blocks = blocks.shape[0]

    # Scale by per-block absmax
    result = blocks * absmax[:n_blocks].unsqueeze(1)
    result = result.reshape(-1)[:n]
    result = result.reshape(quant_state.shape).to(quant_state.dtype)

    return result


def compute_memory_bits_per_param(
    blocksize: int = 64,
    double_quant: bool = False,
    dq_blocksize: int = 256,
) -> float:
    """Compute average bits per parameter including overhead."""
    if not double_quant:
        # 4 bits per weight + one float32 absmax per block
        return 4.0 + 32.0 / blocksize
    else:
        # 4 bits per weight + 8-bit absmax per block + float32 second-level per dq block
        return 4.0 + 8.0 / blocksize + 32.0 / (blocksize * dq_blocksize)
'''

with open("/app/quantlib/core.py", "w") as f:
    f.write(IMPLEMENTATION)

print("Implementation written to /app/quantlib/core.py")

# Quick smoke test
import sys
sys.path.insert(0, "/app")
import torch
from quantlib.core import create_nf4_map, create_fp4_map, quantize_4bit, dequantize_4bit, compute_memory_bits_per_param

# Test NF4 map
nf4 = create_nf4_map()
assert nf4.shape == (16,), f"NF4 shape: {nf4.shape}"
assert len(torch.unique(nf4)) == 16
print(f"NF4 map: {nf4}")

# Test FP4 map
fp4 = create_fp4_map()
assert fp4.shape == (16,), f"FP4 shape: {fp4.shape}"
print(f"FP4 map: {fp4}")

# Test roundtrip
torch.manual_seed(42)
A = torch.randn(1024, 1024)
packed, state = quantize_4bit(A, blocksize=64, quant_type="nf4")
A_hat = dequantize_4bit(packed, state)
err = (A - A_hat).abs().mean().item()
print(f"NF4 roundtrip error: {err:.6f}")

# Test double quant
packed_dq, state_dq = quantize_4bit(A, blocksize=64, quant_type="nf4", compress_statistics=True)
A_hat_dq = dequantize_4bit(packed_dq, state_dq)
err_dq = (A - A_hat_dq).abs().mean().item()
print(f"Double-quant roundtrip error: {err_dq:.6f}")
assert state_dq.nested
assert state_dq.absmax.dtype == torch.uint8

# Test memory
bits_std = compute_memory_bits_per_param(64, False)
bits_dq = compute_memory_bits_per_param(64, True, 256)
print(f"Standard: {bits_std} bits/param, DQ: {bits_dq} bits/param")

print("All smoke tests passed!")
