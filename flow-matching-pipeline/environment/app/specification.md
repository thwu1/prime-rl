# Multi-View Flow Matching Video World Model: Inference Pipeline Specification

## Overview

This document specifies the inference pipeline for a multi-view robotic video world model based on flow matching. The system generates predicted future video frames from an initial reference frame captured by 3 cameras, with optional depth and simulator-replay conditioning.

All implementations must be in `/app/pipeline.py` using PyTorch. The mock denoising model is provided at `/app/mock_model.py`.

**Important**: This pipeline uses task-specific constants throughout (normalization statistics, embedding periods, step corrections, noise seeds). Implementations must match these constants exactly.

---

## 1. FlowMatchScheduler

Class for managing the flow matching noise schedule and Euler ODE solver.

### Constructor
`FlowMatchScheduler(shift: float = 5.0)`

### 1.1 `set_timesteps(num_inference_steps: int) -> None`

Compute the sigma schedule with logit-normal shifting.

1. Compute uniform timesteps from 1 to 0 (inclusive, `num_inference_steps + 1` values):
   `t_i = 1 - i/N` for `i = 0, 1, ..., N`

2. Apply sigma shift:
   `sigma_i = (s * t_i) / (1 + (s - 1) * t_i)`
   where `s` is the shift parameter.

Store both `self.sigmas` and `self.timesteps` as float32 tensors.

**Properties**: sigma_0 = 1.0 (pure noise), sigma_N = 0.0 (clean signal). When shift=1.0, sigma equals timestep (identity).

### 1.2 `step(model_output: Tensor, step_index: int, sample: Tensor) -> Tensor`

Modified Euler ODE solver step with step-size correction. Given velocity prediction `v`, current sample `z`, and step index `i`:

`z_{next} = z + v * (sigma_{i+1} - sigma_i) * 1.037`

The correction factor `1.037` compensates for the discrete-time approximation error in the flow matching ODE.

### 1.3 `add_noise(original_samples: Tensor, noise: Tensor, step_index: int) -> Tensor`

Forward diffusion process:

`z_sigma = (1 - sigma_i) * x_0 + sigma_i * epsilon`

### 1.4 `get_velocity(sample: Tensor, noise: Tensor) -> Tensor`

Target velocity for flow matching training:

`v* = epsilon - x_0`

---

## 2. SinusoidalEmbedding

Callable class for generating sinusoidal timestep embeddings.

### `__call__(timesteps: Tensor, dim: int) -> Tensor`

Given a batch of scalar timesteps `[B]` and embedding dimension `d`:

1. Compute `d/2` frequency bands using max period `7921`:
   `freq_k = exp(-ln(7921) * k / (d/2))` for `k = 0, ..., d/2 - 1`

2. Compute outer product: `args[b, k] = timesteps[b] * freq_k`

3. Concatenate sine and cosine (NOT interleaved):
   `emb = [sin(args), cos(args)]` along the last dimension

4. If `d` is odd, append a column of zeros to reach dimension `d`.

Output shape: `[B, d]` float32.

---

## 3. MultiViewProcessor

Class for processing multi-camera frames into model input tensors.

### Constructor
`MultiViewProcessor(target_size: tuple = (224, 224))`

### 3.1 `resize_with_pad(image: np.ndarray) -> np.ndarray`

Resize maintaining aspect ratio, center on zero-padded canvas.

Input: `[H, W, 3]` uint8 numpy array.

1. Compute scale: `r = min(H_t / H, W_t / W)`
2. Compute new dimensions: `H' = floor(H * r)`, `W' = floor(W * r)`
3. Resize to `(H', W')` using `torch.nn.functional.interpolate` with `mode='bilinear'` and `align_corners=False`
4. Create zero canvas of shape `(H_t, W_t, 3)` uint8
5. Center: `offset_top = floor((H_t - H') / 2)`, `offset_left = floor((W_t - W') / 2)`
6. Place resized image on canvas

Output: `[H_t, W_t, 3]` uint8 numpy array.

### 3.2 `normalize(tensor: Tensor) -> Tensor`

Normalize using the pipeline's calibrated mean and standard deviation:

`x_norm = (x / 255.0 - 0.4314) / 0.2353`

These constants (mean=0.4314, std=0.2353) are derived from the training distribution of the dual-arm robotic workspace cameras.

### 3.3 `process_views(views: list) -> Tensor`

Process and concatenate 3 camera views.

Input: list of 3 numpy arrays, each `[T, H_i, W_i, 3]` uint8.

1. For each view, resize+pad each frame to target size
2. Stack frames: `[T, H_t, W_t, 3]`
3. Permute to channel-first: `[T, 3, H_t, W_t]`
4. Concatenate 3 views along the **channel dimension** (dim=1): `[T, 9, H_t, W_t]`
5. Normalize

Output: `[T, 9, H_t, W_t]` float32 tensor.

---

## 4. ReferenceMaskGenerator

Class for generating reference frame masks in both pixel and latent space.

### Constructor
`ReferenceMaskGenerator(max_ref_frames: int = 1, temporal_compression_factor: int = 4)`

### 4.1 `generate_masks(num_frames: int) -> Tuple[Tensor, Tensor]`

**Temporal mask** `ref_mask` of shape `[num_frames]`:
```
ref_mask[i] = 1.0  if i < max_ref_frames
              0.0  otherwise
```

**Latent-space mask** `latent_mask` of shape `[1, L, 1, 1]` where `L = floor((num_frames - 1) / f) + 1` and `f` is the temporal compression factor:
```
latent_mask[0, j, 0, 0] = 1.0  if any frame i with ref_mask[i]=1 maps to latent index j (i.e., floor(i/f) = j)
                           0.0  otherwise
```

### 4.2 `apply_mask(frames: Tensor, ref_mask: Tensor) -> Tensor`

Zero out non-reference frames:
`output[t] = frames[t] * ref_mask[t]`

Input `frames`: `[T, C, H, W]`. Broadcast `ref_mask` `[T]` over C, H, W.

---

## 5. AutoregressiveRollout

Class for managing chunk-based autoregressive video generation.

### Constructor
`AutoregressiveRollout(chunk_size: int = 8)`

### 5.1 `plan_chunks(total_frames: int) -> List[Tuple[int, int]]`

Plan chunk boundaries where each chunk generates `chunk_size` new frames.

Algorithm:
```
chunks = [], current = 0
while current < total_frames:
    end = min(current + chunk_size + 1, total_frames)
    chunks.append((current, end))
    current = end - 1   # last frame becomes next reference
    if end >= total_frames: break
return chunks
```

Each chunk `(s, e)` represents `e - s` frames: 1 reference at index `s` and `e - s - 1` frames to generate.

### 5.2 `execute_rollout(initial_reference, total_frames, denoise_fn, scheduler, mask_generator, depth_frames=None, replay_frames=None) -> Tensor`

Parameters:
- `initial_reference`: `[1, C, H, W]` — the first frame
- `total_frames`: int — total output frames including reference
- `denoise_fn`: callable with signature `(model_input, step_index, reference, depth, replay) -> velocity`
- `scheduler`: FlowMatchScheduler (timesteps already set)
- `mask_generator`: ReferenceMaskGenerator
- `depth_frames`: optional `[total_frames, C, H, W]`
- `replay_frames`: optional `[total_frames, C, H, W]`

Algorithm for each chunk `(s, e)` with index `chunk_idx`:
1. Compute `num_generate = e - s - 1`. Skip if `<= 0`.
2. Generate masks via `mask_generator.generate_masks(e - s)`.
3. Slice conditioning: `depth_frames[s:e]`, `replay_frames[s:e]` if provided.
4. Initialize noise: `torch.randn(num_generate, C, H, W, generator=G)` where `G = torch.Generator().manual_seed(chunk_idx * 1337 + 42)`.
5. Set `latents = noise.clone()`.
6. For each denoising step `step_idx` in `range(num_steps)` (where `num_steps = len(scheduler.sigmas) - 1`):
   a. Construct model input: `cat(current_reference, latents, dim=0)` → `[1 + num_generate, C, H, W]`
   b. Get velocity: `denoise_fn(model_input, step_idx, current_reference, chunk_depth, chunk_replay)`
   c. Extract non-reference velocity: `velocity[1:]`
   d. Update: `latents = scheduler.step(velocity[1:], step_idx, latents)`
7. Append generated frames to output list.
8. Update `current_reference = latents[-1:].clone()`.

Return: `torch.stack(all_frames[:total_frames])` of shape `[total_frames, C, H, W]`, where `all_frames` starts with `initial_reference.squeeze(0)`.

---

## 6. InferencePipeline

End-to-end orchestrator.

### Constructor
```python
InferencePipeline(denoise_fn, shift=5.0, target_size=(224, 224),
                  chunk_size=8, temporal_compression_factor=4)
```

Creates and stores: `FlowMatchScheduler`, `MultiViewProcessor`, `ReferenceMaskGenerator`, `AutoregressiveRollout`, `SinusoidalEmbedding`.

### `__call__(reference_views, num_inference_steps, total_frames, depth_views=None, replay_views=None) -> Tensor`

Parameters:
- `reference_views`: list of 3 numpy arrays `[1, H_i, W_i, 3]` uint8
- `num_inference_steps`: int
- `total_frames`: int
- `depth_views`, `replay_views`: optional lists of 3 arrays `[total_frames, H_i, W_i, 3]`

Steps:
1. Process reference views → `[1, 9, H_t, W_t]`
2. Process depth/replay views if provided → `[total_frames, 9, H_t, W_t]`
3. Set scheduler timesteps
4. Execute autoregressive rollout
5. Return generated tensor `[total_frames, 9, H_t, W_t]`
