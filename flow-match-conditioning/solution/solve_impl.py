#!/usr/bin/env python3

"""World Model Inference Planner — Complete implementation."""

import sys
import os
import glob
import struct
import zlib
import sqlite3

import numpy as np
import yaml

sys.path.insert(0, "/app")


def _ceil_multiple(x, f):
    """Round x up to the nearest multiple of f."""
    return ((x + f - 1) // f) * f


def parse_wme(filepath):
    """Parse a .wme binary episode file with CRC32 validation."""
    with open(filepath, "rb") as fh:
        raw = fh.read()

    # Validate CRC: last 4 bytes are the checksum
    if len(raw) < 36:
        raise ValueError("File too short to contain a valid WME header + CRC")

    stored_crc = struct.unpack_from("<I", raw, len(raw) - 4)[0]
    computed_crc = zlib.crc32(raw[:-4]) & 0xFFFFFFFF
    if stored_crc != computed_crc:
        raise ValueError(
            f"CRC32 mismatch: stored={stored_crc:#010x}, "
            f"computed={computed_crc:#010x}"
        )

    # Parse header (32 bytes)
    magic, version, num_views, num_frames, traj_dim, fps, _ = struct.unpack_from(
        "<4sHHIHH16s", raw, 0
    )
    if magic != b"WME1":
        raise ValueError(f"Bad magic: {magic!r}")

    offset = 32

    # Parse view metadata (48 bytes each)
    views = []
    for _ in range(num_views):
        name_raw, w, h, fx, fy, cx, cy, _ = struct.unpack_from(
            "<16sIIffff8s", raw, offset
        )
        name = name_raw.split(b"\x00", 1)[0].decode("ascii")
        views.append({
            "name": name,
            "width": w,
            "height": h,
            "fx": float(fx),
            "fy": float(fy),
            "cx": float(cx),
            "cy": float(cy),
        })
        offset += 48

    # Parse trajectory (float32 array)
    traj_bytes = num_frames * traj_dim * 4
    trajectory = np.frombuffer(raw, dtype=np.float32, count=num_frames * traj_dim,
                               offset=offset).reshape(num_frames, traj_dim).copy()
    offset += traj_bytes

    # Skip frame index table (uint64 per frame*view)
    # offset += num_frames * num_views * 8

    return {
        "version": version,
        "num_frames": num_frames,
        "num_views": num_views,
        "trajectory_dim": traj_dim,
        "fps": fps,
        "views": views,
        "trajectory": trajectory,
    }


def compute_multiview_geometry(views, temporal_factor, spatial_factor):
    """Compute multi-view aligned latent geometry with crop coordinates."""
    sf = spatial_factor

    # Padded height: max height rounded up to multiple of spatial_factor
    max_h = max(v["height"] for v in views)
    padded_height = _ceil_multiple(max_h, sf)

    # Per-view padded widths
    padded_widths = [_ceil_multiple(v["width"], sf) for v in views]
    total_width = sum(padded_widths)

    # Compute per-view crop coordinates
    view_crops = []
    pixel_w = 0
    for i, v in enumerate(views):
        pw = padded_widths[i]
        crop = {
            "pixel_w_start": pixel_w,
            "pixel_w_end": pixel_w + pw,
            "pixel_h_content": v["height"],
            "latent_w_start": pixel_w // sf,
            "latent_w_end": (pixel_w + pw) // sf,
            "latent_h_content": v["height"] // sf,
        }
        view_crops.append(crop)
        pixel_w += pw

    return {
        "padded_height": padded_height,
        "total_width": total_width,
        "view_crops": view_crops,
    }


def plan_chunks(trajectory, config, padded_height, total_width):
    """Generate autoregressive chunk schedule with adaptive denoising parameters."""
    cfg_pipe = config["pipeline"]
    cfg_vid = config["video"]
    cfg_vae = config["vae"]

    stride = cfg_vid["stride"]
    start = cfg_vid["start"]
    chunk_size = cfg_vid["chunk_size"]
    overlap = cfg_vid["overlap"]
    min_chunk_frames = cfg_vid["min_chunk_frames"]

    num_frames = trajectory.shape[0]
    tf = cfg_vae["temporal_factor"]
    sf = cfg_vae["spatial_factor"]

    # Generate all sampled frame indices
    all_frame_indices = np.arange(start, num_frames, stride)
    n_s = len(all_frame_indices)

    if n_s == 0:
        return []

    # Generate raw chunk boundaries
    step = chunk_size - overlap
    raw_chunks = []
    k = 0
    while k * step < n_s:
        s = k * step
        e = min(s + chunk_size, n_s)
        raw_chunks.append((s, e))
        k += 1

    # Merge short last chunk
    if len(raw_chunks) > 1:
        last_s, last_e = raw_chunks[-1]
        if last_e - last_s < min_chunk_frames:
            prev_s, _ = raw_chunks[-2]
            raw_chunks[-2] = (prev_s, last_e)
            raw_chunks.pop()

    # Compute adaptive parameters for each chunk
    result = []
    latent_h = padded_height // sf
    latent_w = total_width // sf

    for ci, (s, e) in enumerate(raw_chunks):
        nf = e - s
        episode_frames = all_frame_indices[s:e]
        chunk_traj = trajectory[episode_frames].astype(np.float64)

        # Action variance: mean of per-dimension population variance
        action_var = float(np.mean(np.var(chunk_traj, axis=0, ddof=0)))

        # Normalized variance
        normalized_var = min(action_var / cfg_pipe["var_scale"], 1.0)

        # Flow shift
        flow_shift = cfg_pipe["base_shift"] * (
            1.0 + cfg_pipe["shift_sensitivity"] * normalized_var
        )

        # Number of steps
        num_steps = int(round(
            cfg_pipe["min_steps"]
            + (cfg_pipe["max_steps"] - cfg_pipe["min_steps"]) * normalized_var
        ))
        num_steps = max(cfg_pipe["min_steps"], min(cfg_pipe["max_steps"], num_steps))

        # Stage boundary
        stage_boundary = int(num_steps * cfg_pipe["boundary_ratio"])

        # Latent temporal dimension
        latent_t = (nf - 1) // tf + 1

        result.append({
            "chunk_index": ci,
            "sample_start": s,
            "sample_end": e,
            "num_sampled_frames": nf,
            "frame_indices": episode_frames,
            "num_steps": num_steps,
            "flow_shift": flow_shift,
            "stage_boundary": stage_boundary,
            "action_variance": action_var,
            "latent_t": latent_t,
            "latent_h": latent_h,
            "latent_w": latent_w,
        })

    return result


def build_plan_database(episode_paths, config, db_path):
    """Process all episodes and build the inference plan database."""
    cfg_vae = config["vae"]
    tf = cfg_vae["temporal_factor"]
    sf = cfg_vae["spatial_factor"]

    # Remove existing database if present
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Initialize schema
    with open("/app/schema.sql") as f:
        schema = f.read()
    cur.executescript(schema)

    for ep_path in episode_paths:
        ep = parse_wme(ep_path)
        geo = compute_multiview_geometry(ep["views"], tf, sf)
        chunks = plan_chunks(ep["trajectory"], config,
                             geo["padded_height"], geo["total_width"])

        # Insert episode
        cur.execute(
            "INSERT INTO episodes (filepath, num_frames, num_views, trajectory_dim, fps) "
            "VALUES (?, ?, ?, ?, ?)",
            (ep_path, ep["num_frames"], ep["num_views"], ep["trajectory_dim"], ep["fps"]),
        )
        ep_id = cur.lastrowid

        # Insert views
        for vi, v in enumerate(ep["views"]):
            cur.execute(
                "INSERT INTO views (episode_id, view_index, name, width, height, "
                "fx, fy, cx, cy) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ep_id, vi, v["name"], v["width"], v["height"],
                 v["fx"], v["fy"], v["cx"], v["cy"]),
            )

        # Insert chunks
        for c in chunks:
            cur.execute(
                "INSERT INTO chunks (episode_id, chunk_index, sample_start, sample_end, "
                "num_sampled_frames, num_steps, flow_shift, stage_boundary, "
                "action_variance, latent_t, latent_h, latent_w) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ep_id, c["chunk_index"], c["sample_start"], c["sample_end"],
                 c["num_sampled_frames"], c["num_steps"], c["flow_shift"],
                 c["stage_boundary"], c["action_variance"],
                 c["latent_t"], c["latent_h"], c["latent_w"]),
            )

        # Insert geometry
        cur.execute(
            "INSERT INTO geometry (episode_id, padded_height, total_width, num_views) "
            "VALUES (?, ?, ?, ?)",
            (ep_id, geo["padded_height"], geo["total_width"], len(ep["views"])),
        )

        # Insert view crops
        for vi, vc in enumerate(geo["view_crops"]):
            cur.execute(
                "INSERT INTO view_crops (episode_id, view_index, pixel_w_start, "
                "pixel_w_end, pixel_h_content, latent_w_start, latent_w_end, "
                "latent_h_content) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ep_id, vi, vc["pixel_w_start"], vc["pixel_w_end"],
                 vc["pixel_h_content"], vc["latent_w_start"], vc["latent_w_end"],
                 vc["latent_h_content"]),
            )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    with open("/app/config.yaml") as f:
        config = yaml.safe_load(f)

    episode_paths = sorted(glob.glob("/app/episodes/*.wme"))
    db_path = config["output"]["database"]
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    build_plan_database(episode_paths, config, db_path)
    print(f"Plan database written to {db_path}")
