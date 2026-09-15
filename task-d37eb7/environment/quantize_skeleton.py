"""NF4 (NormalFloat4) Quantization Library

Implement block-wise 4-bit quantization using the NF4 data type with optional
double quantization for memory-efficient model weight compression.

Reference: QLoRA - Efficient Finetuning of Quantized LLMs (arXiv:2305.14314)
Reference: 8-Bit Optimizers via Block-wise Quantization (arXiv:2110.02861)
"""


import numpy as np
import json


def create_nf4_map(offset=0.9677083):
    """Create the NormalFloat4 quantization map.

    The NF4 data type uses quantiles of the standard normal distribution N(0, 1)
    to define 16 quantization levels that are information-theoretically optimal
    for normally distributed data. Each quantization bin captures equal
    probability mass under the normal distribution.

    The type is asymmetric to include an exact zero representation:
    - Positive side: compute norm.ppf at 8 evenly spaced quantile points from
      `offset` down toward 0.5 (exclusive), yielding 8 positive values.
    - Negative side: compute -norm.ppf at 7 evenly spaced quantile points from
      `offset` down toward 0.5 (exclusive), yielding 7 negative values.
    - Add zero for 16 total values.

    Normalize all values to [-1, 1] by dividing by the absolute maximum.
    Return sorted.

    Args:
        offset: The outermost quantile boundary. norm.ppf(offset) gives the
                largest bin edge in standard deviations. The default 0.9677083
                covers ~1.845 standard deviations.

    Returns:
        numpy float32 array of 16 sorted values in [-1, 1]
    """
    raise NotImplementedError("Implement NF4 map construction")


def create_dynamic_map(signed=True, max_exponent_bits=7, total_bits=8):
    """Create the dynamic quantization map for 8-bit block-wise quantization.

    The dynamic data type uses a variable-precision representation that covers
    multiple orders of magnitude. Construction:

    non_sign_bits = total_bits - 1

    For each exponent level i = 0, 1, ..., max_exponent_bits - 1:
      fraction_items = 2^(i + non_sign_bits - max_exponent_bits) + 1  [if signed]
                     = 2^(i + non_sign_bits - max_exponent_bits + 1) + 1  [if unsigned]
      Create fraction_items evenly spaced boundaries from 0.1 to 1.0
      Take midpoints of adjacent boundaries as representative values
      Scale these midpoints by 10^(-(max_exponent_bits - 1) + i)
      If signed, also include negated copies of these scaled values

    If additional_items = 2^(non_sign_bits - max_exponent_bits) - 1 > 0:
      Add more items using the same pattern at the last exponent's scale factor.

    Append 0 and 1.0, then sort. Result: 2^total_bits values, zero-padded to 256.

    Args:
        signed: Whether to include negative values
        max_exponent_bits: Maximum number of exponent bits
        total_bits: Total bits per value

    Returns:
        numpy float32 array of 256 sorted values
    """
    raise NotImplementedError("Implement dynamic map construction")


def pack_4bit(indices):
    """Pack an array of 4-bit indices into uint8 bytes.

    Each pair of consecutive 4-bit values is packed into one uint8 byte.
    Convention: first value in low nibble (bits 0-3), second in high nibble (bits 4-7).
    packed_byte = (second << 4) | first

    If the input has odd length, pad with a zero index.

    Args:
        indices: uint8 numpy array with values in [0, 15]

    Returns:
        uint8 numpy array of ceil(len(indices)/2) packed bytes
    """
    raise NotImplementedError("Implement 4-bit packing")


def unpack_4bit(packed, count=None):
    """Unpack uint8 bytes back to 4-bit indices.

    Reverses pack_4bit. Each byte yields two 4-bit values:
    first = byte & 0x0F (low nibble), second = (byte >> 4) & 0x0F (high nibble).

    Args:
        packed: uint8 numpy array of packed bytes
        count: if specified, return only the first `count` indices

    Returns:
        uint8 numpy array of 4-bit indices
    """
    raise NotImplementedError("Implement 4-bit unpacking")


def quantize_nf4(tensor, blocksize=64, compress_statistics=False, dq_blocksize=256):
    """Quantize a float tensor using block-wise NF4 quantization.

    Algorithm:
    1. Flatten the input and pad to a multiple of blocksize with zeros
    2. Divide into blocks, compute per-block absolute maximum (absmax)
    3. Normalize each block to [-1, 1] by dividing by absmax
    4. For each normalized value, find the nearest NF4 quantization level index
    5. Pack the 4-bit indices two per byte

    If compress_statistics is True (double quantization):
    - Compute offset = mean of absmax values
    - Subtract offset from absmax (centering around zero)
    - Quantize centered absmax using 8-bit dynamic block-wise quantization
      with blocksize = dq_blocksize

    Args:
        tensor: numpy array to quantize (any shape)
        blocksize: values per quantization block (default 64)
        compress_statistics: enable double quantization of absmax
        dq_blocksize: blocksize for double quantization (default 256)

    Returns:
        dict (quant_state) with keys:
            packed_data: uint8 packed 4-bit indices
            absmax: float32 (or uint8 if compressed) block maxima
            quant_map: float32[16] NF4 levels
            original_shape: tuple
            blocksize: int
            total_elements: int (padded count)
            compress_statistics: bool
        If compress_statistics, additionally:
            nested_absmax: float32 per-block maxima from DQ
            nested_quant_map: float32[256] dynamic map
            offset: float32 mean of original absmax
            dq_blocksize: int
            num_absmax: int (absmax count before DQ padding)
    """
    raise NotImplementedError("Implement NF4 quantization")


def dequantize_nf4(quant_state):
    """Dequantize an NF4 quant_state back to float32.

    Algorithm:
    1. Unpack 4-bit indices from packed bytes
    2. If compressed: reconstruct absmax via double dequantization
       (lookup dynamic map values, scale by nested absmax, add offset)
    3. Lookup NF4 levels from indices
    4. Reshape into blocks, multiply by absmax
    5. Remove padding, reshape to original shape

    Args:
        quant_state: dict as returned by quantize_nf4

    Returns:
        float32 numpy array with original shape
    """
    raise NotImplementedError("Implement NF4 dequantization")


def compute_memory_bytes(num_params, blocksize=64, double_quant=False, dq_blocksize=256):
    """Compute the exact memory footprint for NF4-quantized parameters.

    Components:
    - Weights: 4 bits per param = ceil(num_params / 2) bytes
    - Without double quant: absmax = ceil(num_params/blocksize) * 4 bytes (float32)
    - With double quant: absmax = ceil(num_params/blocksize) * 1 byte (uint8)
      + ceil(ceil(num_params/blocksize) / dq_blocksize) * 4 bytes (nested float32)

    Args:
        num_params: total parameter count
        blocksize: NF4 block size (default 64)
        double_quant: whether double quantization is used
        dq_blocksize: blocksize for double quantization (default 256)

    Returns:
        int: total bytes
    """
    raise NotImplementedError("Implement memory calculation")
