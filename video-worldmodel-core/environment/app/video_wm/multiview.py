"""
Multi-View Camera Frame Assembly.

Implements aspect-ratio preserving resize with center padding,
three-camera horizontal concatenation, and image normalization
for the robotic manipulation world model.

See SPEC.md Section 7 for mathematical specification.
"""

import torch
import torch.nn.functional as F


def resize_with_pad(
    image: torch.Tensor,
    target_h: int,
    target_w: int,
) -> torch.Tensor:
    """Resize image preserving aspect ratio and center-pad to target size.

    The resized image must fit entirely within the target canvas -- neither
    dimension may exceed the target. Choose the scale factor accordingly.

    Args:
        image: Input image tensor of shape (C, H, W).
        target_h: Target height.
        target_w: Target width.

    Returns:
        Padded image tensor of shape (C, target_h, target_w).
    """
    raise NotImplementedError("Implement resize_with_pad")


def concatenate_views(
    cam_high: torch.Tensor,
    cam_left: torch.Tensor,
    cam_right: torch.Tensor,
) -> torch.Tensor:
    """Horizontally concatenate three camera views.

    Args:
        cam_high: High camera view of shape (C, H, W).
        cam_left: Left wrist camera view of shape (C, H, W).
        cam_right: Right wrist camera view of shape (C, H, W).

    Returns:
        Concatenated tensor of shape (C, H, 3*W).
    """
    raise NotImplementedError("Implement concatenate_views")


def normalize_image(image: torch.Tensor) -> torch.Tensor:
    """Normalize image from [0, 255] range to [-1, 1] range.

    Args:
        image: Input image tensor with values in [0, 255].

    Returns:
        Normalized tensor with values in [-1, 1].
    """
    raise NotImplementedError("Implement normalize_image")
