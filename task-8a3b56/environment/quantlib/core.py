
"""
4-bit quantization library for neural network weights.

See /app/spec.md for the technical reference.
"""

import torch
from typing import Optional


class QuantState:
    """Container for quantization state needed to dequantize a tensor.

    Attributes:
        absmax: Per-block absolute maximum values.
        shape: Original tensor shape before quantization.
        code: The quantization codebook.
        blocksize: Number of elements per quantization block.
        dtype: Original tensor dtype.
        quant_type: "nf4" or "fp4".
        offset: Offset used in double quantization (or None).
        state2: Second-level QuantState for double quantization (or None).
    """

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
        """True if double quantization was used."""
        return self.state2 is not None


def create_nf4_map(offset: float = 0.9677083) -> torch.Tensor:
    """Create the NormalFloat4 quantization codebook.

    Args:
        offset: Outermost quantile boundary (CDF value).

    Returns:
        Sorted 16-element float32 tensor with values in [-1, 1].
    """
    raise NotImplementedError("Implement NF4 map construction")


def create_fp4_map() -> torch.Tensor:
    """Create the FP4 (4-bit floating point) quantization codebook.

    Returns:
        Sorted 16-element float32 tensor with values in [-1, 1].
    """
    raise NotImplementedError("Implement FP4 map construction")


def quantize_4bit(
    A: torch.Tensor,
    blocksize: int = 64,
    quant_type: str = "nf4",
    compress_statistics: bool = False,
) -> tuple[torch.Tensor, QuantState]:
    """Quantize a tensor to 4-bit values using blockwise quantization.

    Args:
        A: Input tensor (float32, float16, or bfloat16).
        blocksize: Elements per quantization block.
        quant_type: "nf4" or "fp4".
        compress_statistics: Apply double quantization to scaling factors.

    Returns:
        Tuple of (packed uint8 tensor, QuantState).
    """
    raise NotImplementedError("Implement 4-bit blockwise quantization")


def dequantize_4bit(
    A: torch.Tensor,
    quant_state: QuantState,
) -> torch.Tensor:
    """Dequantize a 4-bit packed tensor.

    Args:
        A: Packed uint8 tensor from quantize_4bit().
        quant_state: QuantState from quantize_4bit().

    Returns:
        Dequantized tensor with the original shape and dtype.
    """
    raise NotImplementedError("Implement 4-bit dequantization")


def compute_memory_bits_per_param(
    blocksize: int = 64,
    double_quant: bool = False,
    dq_blocksize: int = 256,
) -> float:
    """Compute the average memory cost in bits per parameter.

    Args:
        blocksize: Primary quantization block size.
        double_quant: Whether double quantization is used.
        dq_blocksize: Block size for second-level quantization.

    Returns:
        Average bits per parameter as a float.
    """
    raise NotImplementedError("Implement memory footprint calculation")
