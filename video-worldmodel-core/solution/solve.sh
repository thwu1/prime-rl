#!/bin/bash


# Deploy all module implementations to /app/video_wm/
cp /solution/rotary_embed_impl.py /app/video_wm/rotary_embed.py
cp /solution/flow_schedule_impl.py /app/video_wm/flow_schedule.py
cp /solution/adaln_impl.py /app/video_wm/adaln.py
cp /solution/rollout_impl.py /app/video_wm/rollout.py
cp /solution/multiview_impl.py /app/video_wm/multiview.py
cp /solution/pipeline_impl.py /app/video_wm/pipeline.py

# Verify all implementations
cd /app && python3 -c "
import sys
sys.path.insert(0, '/app')

from video_wm.rotary_embed import compute_3d_rotary_embeddings, apply_rotary_emb, get_dimension_split
from video_wm.flow_schedule import compute_flow_schedule, compute_mu, compute_image_seq_len, compute_sigma_interpolation
from video_wm.adaln import compute_adaln_modulation, apply_adaln_modulation, rms_norm
from video_wm.rollout import build_rollout_schedule, compute_reference_mask, compute_loss_mask, compute_num_latent_frames, compute_guidance
from video_wm.multiview import resize_with_pad, concatenate_views, normalize_image
from video_wm.pipeline import compute_latent_dimensions, compute_patch_sequence, build_pipeline_config

import torch

# Verify rotary embedding axis ordering
cos, sin = compute_3d_rotary_embeddings(128, 2, 3, 4)
assert cos.shape == (24, 64)
t_dim, h_dim, _ = get_dimension_split(128)
assert torch.allclose(cos[12, t_dim//2:t_dim//2+h_dim//2], torch.ones(h_dim//2), atol=1e-6), 'Rotary axis fix failed'

# Verify mu anchor-point interpolation
assert abs(compute_mu(256) - 0.5) < 1e-6, 'Mu at base failed'
assert abs(compute_mu(4096) - 1.15) < 1e-6, 'Mu at max failed'

# Verify AdaLN modulation order
torch.manual_seed(7)
x = torch.randn(1, 5, 32)
result = apply_adaln_modulation(x, torch.full((1,1,32), 0.5), torch.full((1,1,32), 1.0))
expected = 2.0 * rms_norm(x) + 0.5
assert torch.allclose(result, expected, atol=1e-5), 'AdaLN fix failed'

# Verify guidance direction
uncond = torch.ones(1, 4) * 2.0
cond = torch.ones(1, 4) * 3.0
guided = compute_guidance(uncond, cond, 5.0)
assert torch.allclose(guided, torch.ones(1, 4) * 7.0, atol=1e-6), 'Guidance fix failed'

# Verify resize fit-within
img = torch.ones(3, 240, 320)
result = resize_with_pad(img, 224, 224)
assert result[:, :28, :].abs().max() < 1e-5, 'Resize padding fix failed'

# Verify pipeline orchestration
config = build_pipeline_config()
assert config['latent_dims']['num_latent_frames'] == 9
assert config['sequence_dims']['total_seq_len'] == 5292
assert config['rotary_cos'].shape == (5292, 64)
assert config['denoising_schedule'].shape == (50,)
assert len(config['rollout_schedule']) == 4
assert config['reference_mask'].shape == (9,)
assert config['schedule_mu'] > 0.5

# Verify different resolution
config2 = build_pipeline_config(frame_height=128, frame_width=192)
assert config2['latent_dims']['view_width'] == 576
assert config2['sequence_dims']['total_seq_len'] == 2592

print('All 6 module implementations verified successfully')
"
