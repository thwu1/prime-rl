"""
Multi-View Camera Frame Assembly - Implementation.
"""

import torch
import torch.nn.functional as F


def resize_with_pad(
    image: torch.Tensor,
    target_h: int,
    target_w: int,
) -> torch.Tensor:
    _, h, w = image.shape

    # Scale to fit within target while preserving aspect ratio
    scale = min(target_h / h, target_w / w)
    new_h = int(h * scale)
    new_w = int(w * scale)

    # Bilinear resize
    resized = F.interpolate(
        image.unsqueeze(0),
        size=(new_h, new_w),
        mode="bilinear",
        align_corners=False,
    ).squeeze(0)

    # Center padding
    pad_h = target_h - new_h
    pad_w = target_w - new_w
    pad_top = pad_h // 2
    pad_bottom = pad_h - pad_top
    pad_left = pad_w // 2
    pad_right = pad_w - pad_left

    padded = F.pad(resized, (pad_left, pad_right, pad_top, pad_bottom),
                   mode="constant", value=0.0)
    return padded


def concatenate_views(
    cam_high: torch.Tensor,
    cam_left: torch.Tensor,
    cam_right: torch.Tensor,
) -> torch.Tensor:
    return torch.cat([cam_high, cam_left, cam_right], dim=-1)


def normalize_image(image: torch.Tensor) -> torch.Tensor:
    return (image / 255.0 - 0.5) / 0.5
