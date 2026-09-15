#!/usr/bin/env python3
"""Generate deterministic .wme episode files for the inference planner task."""

import struct
import numpy as np
import zlib
import os


def write_wme(filepath, views, num_frames, trajectory_dim, fps, trajectory):
    """Write a World Model Episode binary file."""
    data = bytearray()

    num_views = len(views)
    # Header: magic(4) + version(2) + num_views(2) + num_frames(4)
    #         + traj_dim(2) + fps(2) + reserved(16) = 32 bytes
    header = struct.pack('<4sHHIHH16s',
                         b'WME1', 1, num_views, num_frames,
                         trajectory_dim, fps, b'\x00' * 16)
    data.extend(header)

    # Per-view metadata: 48 bytes each
    for v in views:
        name_bytes = v['name'].encode('ascii')[:16].ljust(16, b'\x00')
        view_data = struct.pack('<16sIIffff8s',
                                name_bytes, v['width'], v['height'],
                                v['fx'], v['fy'], v['cx'], v['cy'],
                                b'\x00' * 8)
        data.extend(view_data)

    # Trajectory: float32 row-major
    traj_bytes = trajectory.astype(np.float32).tobytes()
    data.extend(traj_bytes)

    # Frame index table: uint64 per (frame, view) pair
    for f in range(num_frames):
        for vi in range(num_views):
            offset = (f * num_views + vi) * 921600
            data.extend(struct.pack('<Q', offset))

    # CRC32 over all preceding bytes
    crc = zlib.crc32(bytes(data)) & 0xFFFFFFFF
    data.extend(struct.pack('<I', crc))

    with open(filepath, 'wb') as fh:
        fh.write(bytes(data))


def main():
    os.makedirs('/app/episodes', exist_ok=True)

    # --- Episode 1: 3 views, 100 frames ---
    rng1 = np.random.RandomState(42)
    traj1 = np.zeros((100, 14), dtype=np.float64)
    # Low-variance region (frames 0-29): gentle sine waves
    for d in range(14):
        traj1[:30, d] = 0.01 * np.sin(np.linspace(0, np.pi, 30) + d * 0.5)
    # Medium-variance region (frames 30-69): random walk
    traj1[30:70] = np.cumsum(rng1.randn(40, 14) * 0.05, axis=0)
    # High-variance region (frames 70-99): aggressive movements
    traj1[70:100] = np.cumsum(rng1.randn(30, 14) * 0.2, axis=0) + traj1[69]
    # Override grippers to constants
    traj1[:, 6] = 0.035
    traj1[:, 13] = 0.069

    views1 = [
        {'name': 'cam_high', 'width': 640, 'height': 480,
         'fx': 500.0, 'fy': 500.0, 'cx': 320.0, 'cy': 240.0},
        {'name': 'cam_left_wrist', 'width': 224, 'height': 224,
         'fx': 200.0, 'fy': 200.0, 'cx': 112.0, 'cy': 112.0},
        {'name': 'cam_right_wrist', 'width': 224, 'height': 224,
         'fx': 200.0, 'fy': 200.0, 'cx': 112.0, 'cy': 112.0},
    ]
    write_wme('/app/episodes/episode_001.wme', views1, 100, 14, 30, traj1)

    # --- Episode 2: 2 views, 37 frames ---
    traj2 = np.zeros((37, 14), dtype=np.float64)
    for d in range(14):
        traj2[:, d] = 0.1 * np.sin(np.linspace(0, 2 * np.pi, 37) + d * 0.3)
    traj2[:, 6] = 0.04
    traj2[:, 13] = 0.05

    views2 = [
        {'name': 'cam_high', 'width': 640, 'height': 480,
         'fx': 500.0, 'fy': 500.0, 'cx': 320.0, 'cy': 240.0},
        {'name': 'cam_front', 'width': 480, 'height': 360,
         'fx': 400.0, 'fy': 400.0, 'cx': 240.0, 'cy': 180.0},
    ]
    write_wme('/app/episodes/episode_002.wme', views2, 37, 14, 15, traj2)

    print("Episodes generated successfully.")


if __name__ == '__main__':
    main()
