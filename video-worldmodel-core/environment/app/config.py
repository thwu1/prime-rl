"""
Configuration parameters for the video world model.
These values are derived from the Wan 2.2 5B video diffusion model
used for robotic manipulation world modeling.
"""

MODEL_CONFIG = {
    "attention_head_dim": 128,
    "num_attention_heads": 40,
    "inner_dim": 5120,  # = 128 * 40
    "num_layers": 40,
    "patch_size_t": 1,
    "patch_size_hw": 2,
    "theta": 10000.0,
    "max_seq_len": 1024,
}

VAE_CONFIG = {
    "z_dim": 16,
    "vae_scale_factor_temporal": 4,
    "vae_scale_factor_spatial": 8,
}

TRAINING_CONFIG = {
    "dst_size": (224, 224),
    "num_frames": 8,
    "rollout": 4,
    "total_frames": 33,  # num_frames * rollout + 1
    "fps": 16,
    "max_ref_frames": 1,
    "ref_factor": 4,
}

INFERENCE_CONFIG = {
    "num_inference_steps": 50,
    "guidance_scale": 5.0,
    "base_shift": 0.5,
    "max_shift": 1.15,
    "base_seq_len": 256,
    "max_seq_len": 4096,
}

LATENT_STATS = {
    "mean": [
        -0.7571, -0.7089, -0.9113, 0.0794, -0.4138, -0.1685, -0.2280, 0.0837,
        -0.2590, -0.5554, -0.0593, -0.2289, -0.2193, 0.0555, -0.3183, -0.2279,
    ],
    "std": [
        6.0659, 5.4227, 4.8424, 4.6975, 4.5760, 4.5334, 4.4651, 4.5908,
        4.3882, 4.2106, 4.5332, 4.2548, 4.3403, 4.2905, 4.1731, 4.0854,
    ],
}
