"""
FlashMLA KV Cache Quantization Routines

Reference source code from the FlashMLA project (https://github.com/deepseek-ai/FlashMLA).
This file implements FP8 quantization for the KV cache used in Multi-head Latent Attention.

NOTE: This code requires PyTorch with CUDA and is provided here as a reference for
understanding the KV cache byte layout. It is NOT intended to be executed directly.
"""
import enum
from typing import Tuple

import torch


class FP8KVCacheLayout(enum.Enum):
    V32_FP8Sparse = 1
    MODEL1_FP8Sparse = 2

    def get_meta(self) -> Tuple[int, int, int, int, int]:
        # Return: (d, d_nope, d_rope, tile_size, num_tiles)
        return {
            FP8KVCacheLayout.V32_FP8Sparse: (576, 512, 64, 128, 4),
            FP8KVCacheLayout.MODEL1_FP8Sparse: (512, 448, 64, 64, 7)
        }[self]


def _cast_scale_inv_to_ue8m0(scales_inv: torch.Tensor, out_dtype=torch.float32) -> torch.Tensor:
    """Cast scale inverse factors to UE8M0 format (power-of-2 values)."""
    return torch.pow(2, torch.clamp_min(scales_inv, 1e-4).log2().ceil()).to(out_dtype)


def quantize_k_cache(
    input_k_cache: torch.Tensor,    # (num_blocks, block_size, h_k, d)
    kvcache_layout: FP8KVCacheLayout,
) -> torch.Tensor:
    """
    Quantize the k-cache into the specified FP8 layout.

    The input tensor is expected to be bfloat16. The output is a byte-packed tensor
    where each token's data occupies bytes_per_token bytes (as float8_e4m3fn elements).
    """
    d, d_nope, d_rope, tile_size, num_tiles = kvcache_layout.get_meta()
    assert input_k_cache.shape[-1] == d
    num_blocks, block_size, h_k, _ = input_k_cache.shape
    assert h_k == 1
    input_k_cache = input_k_cache.squeeze(2)    # [num_blocks, block_size, d]
    input_elem_size = input_k_cache.element_size()

    if kvcache_layout == FP8KVCacheLayout.V32_FP8Sparse:
        # Layout: [d_nope FP8 bytes | num_tiles*4 scale bytes | input_elem_size*d_rope rope bytes]
        bytes_per_token = d_nope + num_tiles*4 + input_elem_size*d_rope
        result = torch.empty((num_blocks, block_size+1, bytes_per_token),
                             dtype=torch.float8_e4m3fn,
                             device=input_k_cache.device)[:, :block_size, :]
        result_k_nope_part = result[..., :d_nope]
        result_k_scale_factor = result[..., d_nope: d_nope + num_tiles*4].view(torch.float32)
        result_k_rope_part = result[..., d_nope + num_tiles*4:].view(input_k_cache.dtype)
        result_k_rope_part[:] = input_k_cache[..., d_nope:]

        for tile_idx in range(0, num_tiles):
            cur_scale_factors_inv = (
                torch.abs(input_k_cache[..., tile_idx*tile_size:(tile_idx+1)*tile_size])
                .max(dim=-1).values.float() / 448.0
            )
            cur_scale_factors_inv = _cast_scale_inv_to_ue8m0(cur_scale_factors_inv)
            result_k_scale_factor[:, :, tile_idx] = cur_scale_factors_inv

            cur_scale_factors_inv.unsqueeze_(-1)
            cur_quantized_nope = (
                input_k_cache[..., tile_idx*tile_size:(tile_idx+1)*tile_size].float()
                / cur_scale_factors_inv.float()
            ).to(torch.float8_e4m3fn)
            result_k_nope_part[..., tile_idx*tile_size:(tile_idx+1)*tile_size] = cur_quantized_nope

        result = result.view(num_blocks, block_size, 1, -1)
        return result

    elif kvcache_layout == FP8KVCacheLayout.MODEL1_FP8Sparse:
        # Layout: [d_nope FP8 | 2*d_rope rope-as-fp8-view | (num_tiles+1) scale bytes]
        bytes_per_token = d_nope + 2*d_rope + num_tiles + 1
        size_per_block_padded = (block_size*bytes_per_token + 576-1) // 576 * 576
        result = torch.empty((num_blocks, size_per_block_padded),
                             dtype=torch.float8_e4m3fn,
                             device=input_k_cache.device)[:, :block_size*bytes_per_token]
        result_k_nope_rope_part = result[:, :block_size*(d_nope+2*d_rope)].view(
            num_blocks, block_size, d_nope + 2*d_rope)
        result_k_nope = result_k_nope_rope_part[:, :, :d_nope]
        result_k_rope = result_k_nope_rope_part[:, :, d_nope:].view(input_k_cache.dtype)
        result_k_scale_factor = (
            result[:, block_size*(d_nope+2*d_rope):]
            .view(num_blocks, block_size, 8)[:, :, :7]
            .view(torch.float8_e8m0fnu)
        )

        result_k_rope[:] = input_k_cache[..., d_nope:]
        for tile_idx in range(0, num_tiles):
            cur_scale_factors_inv = (
                torch.abs(input_k_cache[..., tile_idx*tile_size:(tile_idx+1)*tile_size])
                .max(dim=-1).values.float() / 448.0
            )
            cur_scale_factors_inv = _cast_scale_inv_to_ue8m0(cur_scale_factors_inv)
            result_k_scale_factor[:, :, tile_idx] = cur_scale_factors_inv.to(
                torch.float8_e8m0fnu)

            cur_scale_factors_inv = cur_scale_factors_inv.view(num_blocks, block_size, 1)
            cur_quantized_nope = (
                input_k_cache[..., tile_idx*tile_size:(tile_idx+1)*tile_size].float()
                / cur_scale_factors_inv.float()
            ).to(torch.float8_e4m3fn)
            result_k_nope[:, :, tile_idx*tile_size:(tile_idx+1)*tile_size] = cur_quantized_nope

        result = result.view(num_blocks, block_size, 1, -1)
        return result

    else:
        raise NotImplementedError(f"Unsupported kvcache_layout: {kvcache_layout}")


def dequantize_k_cache(
    quant_k_cache: torch.Tensor,    # (num_blocks, block_size, 1, bytes_per_token)
    kvcache_layout: FP8KVCacheLayout,
) -> torch.Tensor:
    """
    De-quantize the k-cache back to bfloat16.
    """
    d, d_nope, d_rope, tile_size, num_tiles = kvcache_layout.get_meta()
    num_blocks, block_size, h_k, _ = quant_k_cache.shape
    assert h_k == 1
    result = torch.empty((num_blocks, block_size, d),
                         dtype=torch.bfloat16, device=quant_k_cache.device)

    if kvcache_layout == FP8KVCacheLayout.V32_FP8Sparse:
        quant_k_cache = quant_k_cache.view(num_blocks, block_size, -1)

        input_nope = quant_k_cache[..., :d_nope]
        input_scale = quant_k_cache[..., d_nope:d_nope + num_tiles*4].view(torch.float32)
        input_rope = quant_k_cache[..., d_nope + num_tiles*4:].view(torch.bfloat16)
        result[..., d_nope:] = input_rope

        for tile_idx in range(0, num_tiles):
            cur_nope = input_nope[..., tile_idx*tile_size:(tile_idx+1)*tile_size].to(
                torch.float32)
            cur_scales = input_scale[..., tile_idx].unsqueeze(-1)
            result[..., tile_idx*tile_size:(tile_idx+1)*tile_size] = cur_nope * cur_scales

    elif kvcache_layout == FP8KVCacheLayout.MODEL1_FP8Sparse:
        quant_k_cache = quant_k_cache.view(num_blocks, -1)
        input_nope_rope = quant_k_cache[:, :block_size*(d_nope+2*d_rope)].view(
            num_blocks, block_size, d_nope + 2*d_rope)
        input_nope = input_nope_rope[:, :, :d_nope]
        input_rope = input_nope_rope[:, :, d_nope:].view(torch.bfloat16)
        input_scale = (
            quant_k_cache[:, block_size*(d_nope+2*d_rope):]
            .view(num_blocks, block_size, 8)[:, :, :7]
            .view(torch.float8_e8m0fnu)
        )

        result[..., d_nope:] = input_rope
        for tile_idx in range(0, num_tiles):
            cur_nope = input_nope[..., tile_idx*tile_size:(tile_idx+1)*tile_size].to(
                torch.bfloat16)
            cur_scales = input_scale[:, :, tile_idx].to(torch.bfloat16).unsqueeze(-1)
            result[..., tile_idx*tile_size:(tile_idx+1)*tile_size] = cur_nope * cur_scales

    else:
        raise NotImplementedError(f"Unsupported kvcache_layout: {kvcache_layout}")

    result = result.view(num_blocks, block_size, 1, d)
    return result
