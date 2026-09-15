#!/usr/bin/env python3
"""Generate deterministic 3D scene flow evaluation data."""

import os
import numpy as np
import pandas as pd

np.random.seed(42)

SCENE_IDS = [f"scene_{i:03d}" for i in range(8)]
FOREGROUND_CATS = [0, 1, 2, 3, 4]
BACKGROUND_CATS = [5, 6, 7, 8, 9]

os.makedirs("/app/data/annotations", exist_ok=True)
os.makedirs("/app/data/predictions", exist_ok=True)

for scene_id in SCENE_IDS:
    n_points = np.random.randint(600, 1500)

    # Ground truth flow vectors
    gt_flow = np.random.randn(n_points, 3).astype(np.float64)

    # Dynamic vs static: 25-35% dynamic
    dynamic_frac = np.random.uniform(0.25, 0.35)
    is_dynamic = np.random.random(n_points) < dynamic_frac

    # Static points have near-zero flow, dynamic points have larger flow
    gt_flow[~is_dynamic] *= 0.02
    gt_flow[is_dynamic] *= np.random.uniform(0.8, 2.0)

    # Category distribution: 30-50% foreground
    category_indices = np.zeros(n_points, dtype=np.uint8)
    fg_frac = np.random.uniform(0.3, 0.5)
    fg_mask = np.random.random(n_points) < fg_frac
    category_indices[fg_mask] = np.random.choice(FOREGROUND_CATS, fg_mask.sum())
    category_indices[~fg_mask] = np.random.choice(BACKGROUND_CATS, (~fg_mask).sum())

    # Close/far: 60-70% close
    close_frac = np.random.uniform(0.6, 0.7)
    is_close = np.random.random(n_points) < close_frac

    # Validity: 85-95% valid
    valid_frac = np.random.uniform(0.85, 0.95)
    is_valid = np.random.random(n_points) < valid_frac

    # Save ground truth as NPZ
    np.savez(
        f"/app/data/annotations/{scene_id}.npz",
        flow=gt_flow,
        is_dynamic=is_dynamic,
        category_indices=category_indices,
        is_close=is_close,
        is_valid=is_valid,
    )

    # Generate predictions: GT + noise
    noise_scale = np.random.uniform(0.05, 0.2)
    pred_flow = gt_flow + np.random.randn(n_points, 3) * noise_scale

    # Dynamic prediction: flip some labels
    pred_dynamic = is_dynamic.copy()
    flip_rate = np.random.uniform(0.05, 0.15)
    flip_mask = np.random.random(n_points) < flip_rate
    pred_dynamic[flip_mask] = ~pred_dynamic[flip_mask]

    # Save predictions as Apache Feather (float16 flow, bool dynamic)
    df = pd.DataFrame(
        {
            "flow_tx_m": pred_flow[:, 0].astype(np.float16),
            "flow_ty_m": pred_flow[:, 1].astype(np.float16),
            "flow_tz_m": pred_flow[:, 2].astype(np.float16),
            "is_dynamic": pred_dynamic.astype(bool),
        }
    )
    df.to_feather(f"/app/data/predictions/{scene_id}.feather")

print(f"Generated {len(SCENE_IDS)} scene pairs for scene flow evaluation")
