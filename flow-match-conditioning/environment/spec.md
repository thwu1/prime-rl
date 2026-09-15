# World Model Inference Planner — Specification

## Overview

This document specifies the inference planning system for a multi-view video
world model used in robotic manipulation. The planner processes robot episodes
stored in a custom binary format, computes autoregressive denoising schedules
with adaptive parameters, handles multi-view latent geometry alignment, and
stores the complete inference plan in a SQLite database.

Working pipeline primitives are available at `/app/pipeline/`:
- `pipeline.scheduler.compute_sigmas(num_steps, shift)` — shifted flow-matching schedule
- `pipeline.geometry.compute_latent_shape(num_frames, height, width, tf, sf)` — VAE latent dims

Configuration is at `/app/config.yaml`. The database schema is at `/app/schema.sql`.

---

## 1. WME Binary Episode Format

World Model Episode files (`.wme`) store multi-view robot episode data in a
compact binary format with CRC32 integrity checking. All multi-byte fields
use **little-endian** byte order.

### 1.1 File Layout

| Section              | Size (bytes)                              |
|----------------------|-------------------------------------------|
| Header               | 32                                        |
| View metadata        | 48 x num_views                            |
| Trajectory data      | 4 x num_frames x trajectory_dim           |
| Frame index table    | 8 x num_frames x num_views                |
| CRC32 checksum       | 4                                         |

### 1.2 Header (32 bytes)

| Offset | Type      | Field          | Description                            |
|--------|-----------|----------------|----------------------------------------|
| 0      | char[4]   | magic          | Magic bytes: `WME1` (ASCII)            |
| 4      | uint16    | version        | Format version (currently 1)           |
| 6      | uint16    | num_views      | Number of camera views                 |
| 8      | uint32    | num_frames     | Total video frames in the episode      |
| 12     | uint16    | trajectory_dim | Dimensionality of the action vector    |
| 14     | uint16    | fps            | Frames per second                      |
| 16     | bytes[16] | reserved       | Reserved, zero-filled                  |

### 1.3 View Metadata (48 bytes per view)

| Offset | Type      | Field    | Description                   |
|--------|-----------|----------|-------------------------------|
| 0      | char[16]  | name     | View name, null-padded ASCII  |
| 16     | uint32    | width    | Frame width in pixels         |
| 20     | uint32    | height   | Frame height in pixels        |
| 24     | float32   | fx       | Focal length x                |
| 28     | float32   | fy       | Focal length y                |
| 32     | float32   | cx       | Principal point x             |
| 36     | float32   | cy       | Principal point y             |
| 40     | bytes[8]  | reserved | Reserved, zero-filled         |

The `name` field is a fixed 16-byte buffer containing an ASCII string
followed by zero padding.

### 1.4 Trajectory Data

Stored as a contiguous array of **float32** values in row-major order:
`trajectory[frame_idx][dim_idx]`. Total size: `4 x num_frames x trajectory_dim`
bytes.

### 1.5 Frame Index Table

Array of **uint64** values for each (frame, view) pair. Layout:
`table[frame_idx * num_views + view_idx]`. These are metadata-only offsets
used by downstream consumers. Total size: `8 x num_frames x num_views`.

### 1.6 CRC32 Checksum

The final 4 bytes of the file contain a **uint32** CRC32 checksum computed
over all preceding bytes (header through end of frame index table). This uses
the standard CRC32 algorithm (compatible with Python `zlib.crc32`). The parser
**must** validate the checksum and raise a `ValueError` on mismatch.

---

## 2. Chunk Scheduling

### 2.1 Frame Sampling

Given an episode with `F` total frames, the planner samples frames at regular
intervals:

    frame_indices[i] = start + i * stride,    i = 0, 1, 2, ...

continuing while `frame_indices[i] < F`. The total number of sampled frames is:

    N_s = floor((F - 1 - start) / stride) + 1

### 2.2 Chunking with Overlap

The sampled frames are divided into chunks of size `C` (config `video.chunk_size`)
with overlap `O` (config `video.overlap`) frames between consecutive chunks.
The effective step between chunk starts is `S = C - O`.

Chunk `k` covers sampled-frame indices `[k*S, min(k*S + C, N_s))`.

Chunks are generated for `k = 0, 1, 2, ...` while `k * S < N_s`.

### 2.3 Short Chunk Merging

If the last chunk would contain fewer than `min_chunk_frames` (from config
`video.min_chunk_frames`) sampled frames, it is merged into the preceding
chunk by extending that chunk's end boundary to `N_s`.

If only one chunk exists, it is kept as-is regardless of its length.

### 2.4 Adaptive Denoising Parameters

For each chunk covering sampled-frame indices `[s, e)`, the corresponding
episode frame indices are `frame_indices[s], ..., frame_indices[e-1]`. The
trajectory rows at those episode frame indices determine the chunk's
denoising parameters:

1. **Action variance:**
   `action_var = mean(var(trajectory[episode_frames], axis=0))`
   using population variance (ddof=0).

2. **Normalized variance:**
   `normalized_var = min(action_var / var_scale, 1.0)`

3. **Flow shift:**
   `flow_shift = base_shift * (1.0 + shift_sensitivity * normalized_var)`

4. **Number of denoising steps:**
   `num_steps = clip(round(min_steps + (max_steps - min_steps) * normalized_var), min_steps, max_steps)`

5. **Two-stage boundary:**
   `stage_boundary = int(num_steps * boundary_ratio)`
   (Python `int()` truncates toward zero.)

### 2.5 Per-Chunk Latent Dimensions

Each chunk's latent temporal dimension is:

    latent_t = (num_sampled_frames - 1) // temporal_factor + 1

The spatial latent dimensions come from the multi-view geometry (Section 3):

    latent_h = padded_height // spatial_factor
    latent_w = total_width // spatial_factor

---

## 3. Multi-View Latent Geometry

### 3.1 Spatial Alignment

Views may have different resolutions. Before horizontal concatenation they
are spatially aligned:

1. Compute the maximum height across all views.
2. Round up to the nearest multiple of `spatial_factor`:
   `padded_height = ceil_multiple(max_height, spatial_factor)`
   where `ceil_multiple(x, f) = ((x + f - 1) // f) * f`.
3. Round each view's width up to the nearest multiple of `spatial_factor`:
   `padded_width_v = ceil_multiple(width_v, spatial_factor)`.
4. The total concatenated width is:
   `total_width = sum(padded_width_v for all views)`.

### 3.2 Per-View Crop Coordinates

Each view occupies a horizontal band in the concatenated image. Crop
coordinates describe where each view's actual content lies:

**Pixel-space coordinates:**
- `pixel_w_start`: cumulative sum of padded widths of all preceding views.
- `pixel_w_end`: `pixel_w_start + padded_width_v`.
- `pixel_h_content`: the view's original (unpadded) height.

**Latent-space coordinates** (integer division by `spatial_factor`):
- `latent_w_start = pixel_w_start // spatial_factor`
- `latent_w_end = pixel_w_end // spatial_factor`
- `latent_h_content = pixel_h_content // spatial_factor`

---

## 4. SQLite Plan Database

The inference plan is stored in a SQLite database whose schema is defined in
`/app/schema.sql`. The planner must:

1. Create the database file and initialize all tables from the schema.
2. Process each episode file **in the order given**.
3. Populate all five tables:

### 4.1 Table Population

**episodes** — one row per episode:
- `filepath`: the absolute path of the `.wme` file.
- Other fields from the parsed header.

**views** — one row per view per episode:
- `episode_id`: foreign key to `episodes.id`.
- `view_index`: 0-based index within the episode.
- All fields from the parsed view metadata.

**chunks** — one row per chunk per episode:
- `episode_id`: foreign key.
- `chunk_index`: 0-based.
- `sample_start`, `sample_end`: sampled-frame index range `[start, end)`.
- `num_sampled_frames`: `sample_end - sample_start`.
- All adaptive parameters and latent dimensions.

**geometry** — one row per episode:
- `padded_height`, `total_width`, `num_views`.

**view_crops** — one row per view per episode:
- All pixel-space and latent-space crop coordinates.

---

## 5. Required Interface

The orchestrator module (`/app/orchestrator.py`) must export four functions
with the signatures defined in the skeleton file. When executed as a script
(`python3 /app/orchestrator.py`), it must process all `.wme` files in
`/app/episodes/` (sorted alphabetically) and write the plan database to
the path specified in the config.
