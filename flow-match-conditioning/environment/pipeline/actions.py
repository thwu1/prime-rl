"""Robot action parsing and frame sampling for dual-arm manipulation."""

import numpy as np


def parse_dual_arm_action(action):
    """Parse a 14-dimensional action vector into dual-arm components.

    Layout: [left_arm(6), left_gripper(1), right_arm(6), right_gripper(1)]
    """
    return {
        'left_arm': action[:6].copy(),
        'left_gripper': float(action[6]),
        'right_arm': action[7:13].copy(),
        'right_gripper': float(action[13]),
    }


def denormalize_gripper(value, low, high):
    """Map a raw gripper reading from [low, high] to [0, 1] with clipping."""
    result = (value - low) / (high - low)
    return float(np.clip(result, 0.0, 1.0))


def sample_frame_indices(total_frames, num_samples, stride, start):
    """Sample frame indices with fixed stride, clipped to valid range.

    Args:
        total_frames: Length of the source video.
        num_samples: Number of frames to sample.
        stride: Step between consecutive samples.
        start: Index of the first sample.

    Returns:
        int64 array of frame indices.
    """
    indices = start + np.arange(num_samples) * stride
    return np.clip(indices, 0, total_frames - 1).astype(np.int64)
