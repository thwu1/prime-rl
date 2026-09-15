"""World Model Inference Planner — Orchestrator skeleton.

Implement the four functions below. See /app/spec.md for the full specification
and /app/schema.sql for the database schema.

The pipeline modules at /app/pipeline/ provide:
  - pipeline.scheduler.compute_sigmas(num_steps, shift)
  - pipeline.geometry.compute_latent_shape(num_frames, height, width, tf, sf)

When run as a script, this module should process all .wme files in
/app/episodes/ and build the plan database at the path from config.
"""

import sys
import os
import glob
import yaml
import numpy as np
import struct
import zlib
import sqlite3

sys.path.insert(0, '/app')


def parse_wme(filepath):
    """Parse a .wme binary episode file.

    See spec.md Section 1 for the binary format.

    Returns a dict:
        'version': int
        'num_frames': int
        'num_views': int
        'trajectory_dim': int
        'fps': int
        'views': list of dicts with keys:
            'name' (str), 'width' (int), 'height' (int),
            'fx' (float), 'fy' (float), 'cx' (float), 'cy' (float)
        'trajectory': numpy ndarray, shape (num_frames, trajectory_dim), dtype float32

    Must validate CRC32 and raise ValueError on mismatch.
    """
    raise NotImplementedError("Implement WME binary parsing")


def compute_multiview_geometry(views, temporal_factor, spatial_factor):
    """Compute multi-view aligned latent geometry.

    See spec.md Section 3.

    Args:
        views: list of view dicts (from parse_wme)
        temporal_factor: VAE temporal compression factor
        spatial_factor: VAE spatial compression factor

    Returns a dict:
        'padded_height': int
        'total_width': int
        'view_crops': list of dicts with keys:
            'pixel_w_start', 'pixel_w_end', 'pixel_h_content' (ints),
            'latent_w_start', 'latent_w_end', 'latent_h_content' (ints)
    """
    raise NotImplementedError("Implement multi-view geometry")


def plan_chunks(trajectory, config, padded_height, total_width):
    """Generate autoregressive chunk schedule with adaptive denoising parameters.

    See spec.md Sections 2.1-2.5.

    Args:
        trajectory: numpy array (num_frames, trajectory_dim) from parse_wme
        config: parsed YAML config dict
        padded_height: from compute_multiview_geometry
        total_width: from compute_multiview_geometry

    Returns a list of chunk dicts, each with keys:
        'chunk_index': int
        'sample_start': int  (index into sampled-frame array)
        'sample_end': int    (exclusive)
        'num_sampled_frames': int
        'frame_indices': numpy array of episode frame indices for this chunk
        'num_steps': int
        'flow_shift': float
        'stage_boundary': int
        'action_variance': float
        'latent_t': int
        'latent_h': int
        'latent_w': int
    """
    raise NotImplementedError("Implement chunk scheduling")


def build_plan_database(episode_paths, config, db_path):
    """Process all episodes and build the inference plan database.

    See spec.md Section 4.

    Creates the SQLite database at db_path using /app/schema.sql.
    Populates tables: episodes, views, chunks, geometry, view_crops.
    Processes episodes in the order given by episode_paths.

    Args:
        episode_paths: list of .wme file paths
        config: parsed YAML config dict
        db_path: path for the output SQLite database
    """
    raise NotImplementedError("Implement database builder")


if __name__ == '__main__':
    with open('/app/config.yaml') as f:
        config = yaml.safe_load(f)

    episode_paths = sorted(glob.glob('/app/episodes/*.wme'))
    db_path = config['output']['database']
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    build_plan_database(episode_paths, config, db_path)
    print(f"Plan database written to {db_path}")
