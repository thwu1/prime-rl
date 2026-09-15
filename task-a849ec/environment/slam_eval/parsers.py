"""Trajectory file parsers for KITTI, TUM, and EuRoC benchmark formats.

Each parser returns a list of (timestamp_or_index, position_xyz, rotation_3x3) tuples.
"""

import csv
import numpy as np


def quaternion_to_rotation_matrix(qx, qy, qz, qw):
    """Convert quaternion (scalar-last: qx, qy, qz, qw) to 3x3 rotation matrix."""
    n = np.sqrt(qx**2 + qy**2 + qz**2 + qw**2)
    qx, qy, qz, qw = qx / n, qy / n, qz / n, qw / n
    return np.array([
        [1 - 2*(qy**2 + qz**2), 2*(qx*qy - qz*qw), 2*(qx*qz + qy*qw)],
        [2*(qx*qy + qz*qw), 1 - 2*(qx**2 + qz**2), 2*(qy*qz - qx*qw)],
        [2*(qx*qz - qy*qw), 2*(qy*qz + qx*qw), 1 - 2*(qx**2 + qy**2)]
    ])


def parse_kitti(filepath):
    """Parse KITTI trajectory file.

    Each line: 12 space-separated floats, row-major 3x4 [R|t] matrix.
    Poses indexed by line number.
    """
    poses = []
    with open(filepath) as f:
        for idx, line in enumerate(f):
            vals = list(map(float, line.strip().split()))
            if len(vals) != 12:
                continue
            R = np.array([
                [vals[0], vals[1], vals[2]],
                [vals[4], vals[5], vals[6]],
                [vals[8], vals[9], vals[10]]
            ])
            t = np.array([vals[3], vals[7], vals[11]])
            poses.append((float(idx), t, R))
    return poses


def parse_tum(filepath):
    """Parse TUM trajectory file.

    Lines starting with # are comments.
    Data: timestamp tx ty tz qx qy qz qw (quaternion scalar-last).
    """
    poses = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) < 8:
                continue
            ts = float(parts[0])
            pos = np.array([float(parts[1]), float(parts[2]), float(parts[3])])
            R = quaternion_to_rotation_matrix(
                float(parts[4]), float(parts[5]), float(parts[6]), float(parts[7])
            )
            poses.append((ts, pos, R))
    return poses


def parse_euroc_gt(filepath):
    """Parse EuRoC ground truth CSV file.

    CSV columns: timestamp, px, py, pz, qw, qx, qy, qz, velocities, biases...
    Quaternion convention: scalar-first (qw, qx, qy, qz).
    """
    poses = []
    with open(filepath) as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or row[0].strip().startswith('#'):
                continue
            ts = float(row[0])
            px, py, pz = float(row[1]), float(row[2]), float(row[3])
            qw, qx, qy, qz = float(row[4]), float(row[5]), float(row[6]), float(row[7])
            R = quaternion_to_rotation_matrix(qx, qy, qz, qw)
            poses.append((ts, np.array([px, py, pz]), R))
    return poses
