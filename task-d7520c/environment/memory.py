"""
Memory footprint calculator for quantized LLaMA-family models.
"""


def bits_per_parameter(
    quant_bits: int = 4,
    blocksize: int = 64,
    double_quant: bool = False,
    dq_blocksize: int = 256,
) -> float:
    """Calculate effective bits per parameter for a quantization config.

    Args:
        quant_bits: Bits per weight value (e.g., 4 for NF4).
        blocksize: Block size for first-level quantization.
        double_quant: Whether secondary quantization is applied.
        dq_blocksize: Block size for secondary quantization.

    Returns:
        Effective bits per parameter as a float.
    """
    bpp = float(quant_bits)

    if not double_quant:
        bpp += 32.0 / blocksize
    else:
        bpp += 8.0 / blocksize
        bpp += 32.0 / (blocksize + dq_blocksize)

    return bpp


def compute_total_params(model_config: dict) -> int:
    """Compute total parameter count for a LLaMA-style model.

    LLaMA models have no biases in linear layers. Counts embedding,
    LM head, attention projections, and MLP layers. Layer norms are
    excluded (negligible and kept in higher precision).

    Args:
        model_config: Dict with keys 'hidden_size', 'num_layers',
            'num_heads', 'intermediate_size', 'vocab_size'.

    Returns:
        Total parameter count as an integer.
    """
    h = model_config["hidden_size"]
    n_layers = model_config["num_layers"]
    ff = model_config["intermediate_size"]
    v = model_config["vocab_size"]

    embed_params = v * h * 2

    attention_params = 3 * h * h
    mlp_params = 3 * h * ff
    per_layer = attention_params + mlp_params

    return embed_params + n_layers * per_layer


def compute_model_memory(
    model_config: dict,
    precision: str = "fp32",
    blocksize: int = 64,
    double_quant: bool = False,
    dq_blocksize: int = 256,
) -> float:
    """Compute total memory in bytes for a model under given precision.

    Args:
        model_config: Model architecture configuration dict.
        precision: One of 'fp32', 'fp16', 'bf16', 'nf4'.
        blocksize: Block size for NF4 quantization.
        double_quant: Whether to use secondary quantization (NF4 only).
        dq_blocksize: Block size for secondary quantization.

    Returns:
        Total memory in bytes as a float.
    """
    total_params = compute_total_params(model_config)

    precision_bits = {"fp32": 32.0, "fp16": 16.0, "bf16": 16.0}

    if precision in precision_bits:
        bpp = precision_bits[precision]
    elif precision == "nf4":
        bpp = bits_per_parameter(4, blocksize, double_quant, dq_blocksize)
    else:
        raise ValueError(f"Unknown precision: {precision}")

    return total_params * bpp / 8.0


def compute_dq_savings(
    model_config: dict,
    blocksize: int = 64,
    dq_blocksize: int = 256,
) -> float:
    """Compute memory savings from secondary quantization in bytes.

    Args:
        model_config: Model architecture configuration dict.
        blocksize: Block size for first-level quantization.
        dq_blocksize: Block size for secondary quantization.

    Returns:
        Memory savings in bytes as a float.
    """
    total_params = compute_total_params(model_config)

    bpp_no_dq = bits_per_parameter(4, blocksize, False)
    bpp_dq = bits_per_parameter(4, blocksize, True, dq_blocksize)

    return total_params * (bpp_no_dq - bpp_dq) / 8.0
