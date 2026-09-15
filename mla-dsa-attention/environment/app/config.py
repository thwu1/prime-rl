"""GLM-5 model configuration loader.

Reads the active model variant configuration from configs/active_config.json.
"""

import json
import os


class GLM5Config:
    def __init__(self):
        config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "configs")
        active_path = os.path.join(config_dir, "active_config.json")

        if not os.path.exists(active_path):
            raise FileNotFoundError(
                "configs/active_config.json not found. "
                "See /app/Makefile for configuration setup."
            )

        with open(active_path) as f:
            cfg = json.load(f)

        arch = cfg["architecture"]
        latent = cfg["latent_attention"]
        dsa = cfg["dynamic_sparse_attention"]

        self.hidden_size = arch["hidden_size"]
        self.num_attention_heads = arch["num_attention_heads"]
        self.rms_norm_eps = arch["rms_norm_eps"]
        self.max_position_embeddings = arch["max_position_embeddings"]
        self.rope_theta = arch["rope_theta"]

        self.q_lora_rank = latent["q_lora_rank"]
        self.kv_lora_rank = latent["kv_lora_rank"]
        self.qk_rope_head_dim = latent["qk_rope_head_dim"]
        self.qk_nope_head_dim = latent["qk_nope_head_dim"]
        self.qk_head_dim = self.qk_nope_head_dim + self.qk_rope_head_dim
        self.v_head_dim = latent["v_head_dim"]

        self.index_topk = dsa["index_topk"]
        self.index_head_dim = dsa["index_head_dim"]
        self.index_n_heads = dsa["index_n_heads"]
