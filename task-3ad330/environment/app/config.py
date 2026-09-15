"""
GLM-5 Model Configuration (scaled-down for testing).

This configuration mirrors the architectural ratios of GLM-5's Multi-Latent
Attention (MLA) mechanism but with reduced dimensions for CPU-based testing.

GLM-5 full-scale reference:
    hidden_size=6144, num_attention_heads=64, qk_nope_head_dim=192,
    qk_rope_head_dim=64, v_head_dim=256, q_lora_rank=2048, kv_lora_rank=512

"""

from dataclasses import dataclass


@dataclass
class GLM5Config:
    """Configuration for a scaled-down GLM-5-style model."""

    vocab_size: int = 1024
    hidden_size: int = 256
    num_hidden_layers: int = 2
    num_attention_heads: int = 4

    # ---------- MLA (Multi-Latent Attention) dimensions ----------
    # Q/K head dimensions are split into two parts:
    #   - nope: position-invariant dimensions (no rotary embedding)
    #   - rope: dimensions that receive rotary position embedding
    qk_nope_head_dim: int = 48
    qk_rope_head_dim: int = 16

    # Value head dimension (independent of QK head dims)
    v_head_dim: int = 64

    # LoRA-style compression ranks
    # Query path compresses hidden_size -> q_lora_rank -> num_heads * qk_head_dim
    q_lora_rank: int = 128
    # KV path compresses hidden_size -> (kv_lora_rank + qk_rope_head_dim)
    # The kv_lora_rank portion is then expanded to produce both K_nope and V
    kv_lora_rank: int = 64

    # ---------- Rotary Position Embedding ----------
    rope_theta: float = 10000.0
    max_position_embeddings: int = 4096

    # ---------- Dense MLP ----------
    dense_intermediate_size: int = 512

    # ---------- Normalization ----------
    rms_norm_eps: float = 1e-5

    @property
    def qk_head_dim(self) -> int:
        """Total Q/K head dimension = nope + rope."""
        return self.qk_nope_head_dim + self.qk_rope_head_dim
