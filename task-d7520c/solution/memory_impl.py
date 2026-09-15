"""
QLoRA Memory Footprint Calculator — Solution

Calculates memory requirements for different quantization configurations
of LLaMA-family model architectures.
"""


def bits_per_parameter(
    quant_bits: int = 4,
    blocksize: int = 64,
    double_quant: bool = False,
    dq_blocksize: int = 256,
) -> float:
    """Calculate effective bits per parameter for a quantization config."""
    bpp = float(quant_bits)

    if not double_quant:
        # FP32 quantization constants: one per block
        bpp += 32.0 / blocksize
    else:
        # First level: FP8 quantization constants
        bpp += 8.0 / blocksize
        # Second level: FP32 constants for the FP8 constants
        bpp += 32.0 / (blocksize * dq_blocksize)

    return bpp


def compute_total_params(model_config: dict) -> int:
    """Compute total parameter count for a LLaMA-style model."""
    h = model_config["hidden_size"]
    n_layers = model_config["num_layers"]
    ff = model_config["intermediate_size"]
    v = model_config["vocab_size"]

    # Embedding + LM head (no weight tying)
    embed_params = v * h * 2

    # Per transformer layer: QKVO attention + gate/up/down MLP
    attention_params = 4 * h * h
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
    """Compute total memory in bytes for a model under given precision."""
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
    """Compute memory savings from double quantization in bytes."""
    total_params = compute_total_params(model_config)

    bpp_no_dq = bits_per_parameter(4, blocksize, False)
    bpp_dq = bits_per_parameter(4, blocksize, True, dq_blocksize)

    savings_bits = total_params * (bpp_no_dq - bpp_dq)
    return savings_bits / 8.0
