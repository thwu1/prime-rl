# Video World Model: Behavioral Specification

## 1. System Context

This pipeline serves a 3D video diffusion transformer that predicts future frames for a dual-arm robot across three camera views (overhead, left wrist, right wrist). Each module processes data at a specific stage of the inference pipeline. Module function signatures, parameter names, and return types are defined in the stub files under `video_wm/`.

## 2. Configuration

See `config.py` for all parameter values. Key relationships:

- Inner dimension: `inner_dim = attention_head_dim * num_attention_heads`
- Total video frames: `total_frames = num_frames * rollout + 1`
- Multi-view width: `view_width = dst_size[1] * 3` (3 cameras concatenated horizontally)
- Latent spatial dimensions: `latent_h = dst_size[0] / vae_scale_factor_spatial`, `latent_w = view_width / vae_scale_factor_spatial`

## 3. 3D Rotary Position Embeddings (rotary_embed)

### 3.1 Dimension Decomposition

The attention head dimension is split into components for temporal, height, and width axes. See `get_dimension_split` docstring for the exact decomposition rule.

### 3.2 Embedding Computation

`compute_3d_rotary_embeddings` produces cosine and sine tables encoding 3D positions in a video sequence grid.

**Output shape**: `(T * H * W, d // 2)` where T, H, W are the sequence lengths for each axis.

**Required properties**:
- Each axis gets `d_x / 2` independent frequency bands computed from that axis's dimension allocation using the standard RoPE frequency formula with base θ from `config.py`. Use float64 for frequency computation.
- Angle tables for each axis are outer products of integer position indices and the axis's frequency bands.
- The three axes contribute independent angle components, concatenated in order [temporal, height, width] along the frequency dimension.
- Each axis's angles vary only along its own spatial dimension and are constant along the other two.
- The 3D grid is flattened in row-major (C-contiguous) order with axes ordered (T, H, W), giving temporal-major indexing: position (t, h, w) maps to index `t*H*W + h*W + w`.
- At position (0, 0, 0): all angles are zero, hence cos = 1 and sin = 0 for all bands.
- When any coordinate is zero, that axis's angle components are zero, giving cos = 1, sin = 0 for those bands.
- cos² + sin² = 1 everywhere.
- Output dtype is float32.

### 3.3 Rotary Application

`apply_rotary_emb` applies the position embeddings to a query/key tensor of shape `(batch, heads, seq_len, head_dim)`.

**Required properties**:
- Uses the interleaved even/odd rotation scheme (see stub docstring).
- Cos/sin tables are sliced to match `seq_len` and broadcast to match batch and head dimensions.
- The transformation is an isometry: per-position L2 norms are preserved.
- At position (0,0,0) where all angles are zero, the rotation is the identity.

## 4. Flow Matching Schedule (flow_schedule)

### 4.1 Image Sequence Length

After VAE encoding and patch embedding, the transformer's sequence length is computed by dividing each latent dimension by the corresponding patch size and taking the product. All divisions are integer. See `compute_image_seq_len` signature.

### 4.2 Dynamic Shift (mu)

The shift parameter `mu` is a **linear function** of sequence length, anchored at two reference points:

    mu(base_seq_len) = base_shift
    mu(max_seq_len) = max_shift

The value is NOT clamped — mu can exceed max_shift for larger sequences.

Derive the linear function from these two anchor constraints.

### 4.3 Timestep Generation

`compute_flow_schedule` generates shifted denoising timesteps.

**Required properties**:
- N base timesteps are evenly spaced from 1.0 to 1/N (inclusive of both endpoints).
- The `_time_shift` helper (see its docstring for the transformation formula) warps the base timesteps using the computed mu and sigma=1.
- The first timestep is always exactly 1.0 regardless of mu.
- The schedule is monotonically decreasing.
- With mu=0 (both shifts set to 0.0 and seq_len=base_seq_len), the shifted schedule equals the base schedule exactly.

### 4.4 Noise Interpolation

`compute_sigma_interpolation` blends clean latents and noise using parameter sigma.

**Required properties**:
- sigma = 0 → output equals clean latents exactly
- sigma = 1 → output equals noise exactly
- sigma = 0.5 → output is the arithmetic mean of noise and latents
- The interpolation is linear in sigma

## 5. Adaptive Layer Normalization (adaln)

### 5.1 RMS Normalization

See `rms_norm` docstring for the formula. After normalization, the mean of squared values along the last dimension should be approximately 1.0.

### 5.2 Modulation Computation

`compute_adaln_modulation` combines a learnable table `(1, 6, dim)` with a timestep embedding `(batch, 6*dim)` to produce 6 modulation vectors. The table and reshaped embedding are combined additively. The result is split into 6 parts, each of shape `(batch, 1, dim)`. See the stub docstring for output ordering.

### 5.3 Modulation Application

`apply_adaln_modulation` applies shift and scale to an input.

**Required properties**:
- When scale=0 and shift=0: output equals `rms_norm(x)` (normalization only)
- The scale parameter acts multiplicatively on the normalized result, with an identity offset (zero scale means no multiplicative change)
- The shift is added to the result after scaling
- With scale=1.0 and shift=0.5: the output equals `2.0 * rms_norm(x) + 0.5`

Derive the composition formula from these constraints.

## 6. Multi-Step Rollout (rollout)

### 6.1 Latent Frame Count

See `compute_num_latent_frames` docstring for the temporal compression formula.

### 6.2 Rollout Schedule

With R rollout steps of F frames each (total_frames = R * F + 1):

    step_i covers frames [i * F, (i+1) * F]  for i = 0, ..., R-1

### 6.3 Reference Frame Masking

A binary mask tensor of shape `(N_latent,)`:

    mask[0 : max_ref] = 1  (reference frames with ground truth)
    mask[max_ref :]    = 0  (frames to be predicted)

### 6.4 Loss Masking

Per-step loss mask of shape `(N_latent_per_step,)`:

- Step 0: `mask[0:ref_frames] = 0` (reference, no gradient), `mask[ref_frames:] = 1`
- Step i > 0: `mask[0] = 0` (overlap from previous step), `mask[1:] = 1`

### 6.5 Classifier-Free Guidance

`compute_guidance` combines unconditional and conditional noise predictions.

**Required properties**:
- guidance_scale = 0 → output equals the unconditional prediction exactly
- guidance_scale = 1 → output equals the conditional prediction exactly
- guidance_scale > 1 → output extrapolates beyond the conditional prediction, amplifying the direction from unconditional toward conditional
- The combination is linear

Derive the formula from these constraints.

## 7. Multi-View Assembly (multiview)

### 7.1 Resize with Padding

`resize_with_pad` resizes an image to fit within a target canvas, preserving aspect ratio, then center-pads with zeros to reach exact target dimensions.

**Required properties**:
- Output shape is exactly `(C, target_h, target_w)`
- The resized image fits entirely within the target — neither its height nor its width may exceed the corresponding target dimension
- Aspect ratio is preserved
- Bilinear interpolation with `align_corners=False`
- Padding regions contain zeros
- Padding is centered: `floor(remaining / 2)` on top/left, remainder on bottom/right

### 7.2 View Concatenation

Three camera view tensors (each `(C, H, W)`) are concatenated along the width dimension (dim=-1), giving shape `(C, H, 3*W)`.

### 7.3 Image Normalization

Maps pixel values from [0, 255] to [-1, 1]. Black (0) maps to -1, white (255) maps to +1, mid-gray (127.5) maps to 0.

## 8. Pipeline Orchestration (pipeline)

### 8.1 Latent Dimensions

`compute_latent_dimensions` derives the latent space geometry from video parameters. Three camera views are concatenated **horizontally in pixel space** before VAE encoding. The VAE compresses spatial dimensions by integer division and temporal dimensions using the latent frame formula from Section 6.1.

### 8.2 Patch Sequence Dimensions

`compute_patch_sequence` computes transformer token counts by dividing each latent dimension by the corresponding patch size. The total sequence length is the product of all three.

### 8.3 Pipeline Configuration

`build_pipeline_config` orchestrates all other modules. It chains: latent dimension computation → patch sequence computation → rotary embedding generation → flow schedule computation → rollout scheduling → reference mask generation. See the function signature for the complete set of returned keys.
