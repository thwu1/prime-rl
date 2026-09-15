"""
Fix all defects in the registration pipeline:
1. Fix transforms.py (6 bugs + 2 stubs)
2. Fix configs/pipeline.json (ordering + spacing ref)
3. Create validate_pipeline.py
"""

import json

# ---------------------------------------------------------------------------
# 1. Write corrected transforms.py
# ---------------------------------------------------------------------------
corrected_transforms = r'''"""Spatial transform utilities for 3D medical images using NIfTI-style affine matrices."""

import numpy as np
from scipy.ndimage import map_coordinates


def extract_spacing(affine):
    """Extract voxel spacing from a 4x4 affine matrix."""
    return np.sqrt(np.sum(affine[:3, :3] ** 2, axis=0))


def extract_direction(affine):
    """Extract direction cosine matrix from affine."""
    spacing = extract_spacing(affine)
    return affine[:3, :3] / spacing[None, :]


def extract_origin(affine):
    """Extract world coordinate origin from affine."""
    return affine[:3, 3].copy()


def build_affine(spacing, direction, origin):
    """Construct a 4x4 affine from spacing, direction, and origin."""
    spacing = np.asarray(spacing, dtype=float)
    direction = np.asarray(direction, dtype=float)
    origin = np.asarray(origin, dtype=float)
    affine = np.eye(4)
    affine[:3, :3] = direction * spacing[None, :]
    affine[:3, 3] = origin
    return affine


def get_axcodes(affine):
    """Determine axis orientation codes (e.g., 'RAS', 'LPS') from affine."""
    direction = extract_direction(affine)
    codes = ''
    axis_labels = [('R', 'L'), ('A', 'P'), ('S', 'I')]
    for col in range(3):
        abs_col = np.abs(direction[:, col])
        dominant_axis = np.argmax(abs_col)
        if direction[dominant_axis, col] > 0:
            codes += axis_labels[dominant_axis][0]
        else:
            codes += axis_labels[dominant_axis][1]
    return codes


def resample(data, src_affine, target_affine, target_shape, order=1):
    """Resample volume from source to target coordinate system."""
    grid = np.meshgrid(
        np.arange(target_shape[0]),
        np.arange(target_shape[1]),
        np.arange(target_shape[2]),
        indexing='ij'
    )
    n = np.prod(target_shape)
    target_voxels = np.stack(
        [g.ravel() for g in grid] + [np.ones(n)], axis=0
    )
    world = target_affine @ target_voxels
    src_voxels = np.linalg.inv(src_affine) @ world
    coords = [src_voxels[d].reshape(target_shape) for d in range(3)]
    result = map_coordinates(data, coords, order=order, mode='constant', cval=0.0)
    return result


def resample_to_spacing(data, src_affine, new_spacing, order=1):
    """Resample volume to new voxel spacing, preserving world origin and direction."""
    new_spacing = np.asarray(new_spacing, dtype=float)
    src_spacing = extract_spacing(src_affine)
    direction = extract_direction(src_affine)
    origin = extract_origin(src_affine)
    src_shape = np.array(data.shape, dtype=float)
    new_shape = np.round(src_shape * src_spacing / new_spacing).astype(int)
    new_shape = np.maximum(new_shape, 1)
    new_affine = build_affine(new_spacing, direction, origin)
    resampled = resample(data, src_affine, new_affine, tuple(new_shape), order=order)
    return resampled, new_affine


def reorient_to_axcodes(data, src_affine, target_codes):
    """Reorient volume to target axis codes via permutation and flipping."""
    src_codes = get_axcodes(src_affine)
    code_to_axis = {
        'R': (0, False), 'L': (0, True),
        'A': (1, False), 'P': (1, True),
        'S': (2, False), 'I': (2, True),
    }
    src_orients = [code_to_axis[c] for c in src_codes]
    tgt_orients = [code_to_axis[c] for c in target_codes]
    permutation = []
    flips = []
    for tgt_ax, tgt_neg in tgt_orients:
        for src_idx, (src_ax, src_neg) in enumerate(src_orients):
            if src_ax == tgt_ax:
                permutation.append(src_idx)
                flips.append(tgt_neg != src_neg)
                break
    result = np.transpose(data, permutation)
    for ax_idx, flip in enumerate(flips):
        if flip:
            result = np.flip(result, axis=ax_idx)
    result = np.ascontiguousarray(result)
    M = np.zeros((4, 4))
    M[3, 3] = 1
    for new_d in range(3):
        old_d = permutation[new_d]
        if flips[new_d]:
            M[old_d, new_d] = -1
            M[old_d, 3] += data.shape[old_d] - 1
        else:
            M[old_d, new_d] = 1
    new_affine = src_affine @ M
    return result, new_affine


def compose_transforms(affine_list):
    """Compose affine transforms applied left-to-right."""
    result = np.eye(4)
    for aff in affine_list:
        result = aff @ result
    return result


def invert_resample(resampled, resampled_affine, orig_shape, orig_affine, order=1):
    """Recover original volume from resampled version."""
    return resample(resampled, resampled_affine, orig_affine, orig_shape, order=order)


def register_landmarks(src_landmarks, tgt_landmarks):
    """Compute rigid-body registration from paired 3D landmarks."""
    src = np.asarray(src_landmarks, dtype=float)
    tgt = np.asarray(tgt_landmarks, dtype=float)

    c_src = src.mean(axis=0)
    c_tgt = tgt.mean(axis=0)
    src_c = src - c_src
    tgt_c = tgt - c_tgt

    H = src_c.T @ tgt_c
    U, S, Vt = np.linalg.svd(H)

    d = np.linalg.det(Vt.T @ U.T)
    D = np.diag([1.0, 1.0, np.sign(d)])
    R = Vt.T @ D @ U.T

    t = c_tgt - R @ c_src

    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = t
    return M


def evaluate_alignment(data1, affine1, data2, affine2, metric='ncc'):
    """Evaluate alignment quality between two volumes."""
    data2_resampled = resample(data2, affine2, affine1, data1.shape, order=1)

    a = data1.ravel().astype(float)
    b = data2_resampled.ravel().astype(float)

    if metric == 'ncc':
        a_m = a - np.mean(a)
        b_m = b - np.mean(b)
        denom = np.sqrt(np.sum(a_m ** 2) * np.sum(b_m ** 2))
        if denom == 0:
            return 0.0
        return float(np.sum(a_m * b_m) / denom)
    elif metric == 'mse':
        return float(np.mean((a - b) ** 2))
    else:
        raise ValueError(f"Unknown metric: {metric}")
'''

with open('/app/transforms.py', 'w') as f:
    f.write(corrected_transforms)
print("Fixed transforms.py")

# ---------------------------------------------------------------------------
# 2. Fix pipeline configuration
# ---------------------------------------------------------------------------
corrected_pipeline = {
    "name": "registration_pipeline",
    "description": "3D medical image preprocessing and rigid registration",
    "steps": [
        {"name": "orient", "transform": "reorient", "params": {"target_codes": "RAS"}},
        {"name": "resample", "transform": "resample_spacing", "params": {"spacing_ref": "target_spacing"}},
        {"name": "normalize", "transform": "zscore", "params": {}},
        {"name": "register", "transform": "landmark_registration", "params": {}},
        {"name": "evaluate", "transform": "alignment_metric", "params": {"metric": "ncc"}}
    ]
}

with open('/app/configs/pipeline.json', 'w') as f:
    json.dump(corrected_pipeline, f, indent=2)
print("Fixed configs/pipeline.json")

# ---------------------------------------------------------------------------
# 3. Create validate_pipeline.py
# ---------------------------------------------------------------------------
validator_code = r'''#!/usr/bin/env python3
"""Validate a pipeline configuration against ordering constraints in metadata.db."""

import json
import sqlite3
import sys


def validate(pipeline_path, db_path='/app/metadata.db'):
    with open(pipeline_path) as f:
        pipeline = json.load(f)

    steps = [s['name'] for s in pipeline['steps']]

    conn = sqlite3.connect(db_path)
    constraints = conn.execute(
        'SELECT step_before, step_after, reason FROM transform_constraints'
    ).fetchall()
    conn.close()

    violations = []
    for before, after, reason in constraints:
        if before in steps and after in steps:
            if steps.index(before) > steps.index(after):
                violations.append(
                    f"INVALID: '{before}' must precede '{after}' — {reason}"
                )

    if violations:
        for v in violations:
            print(v)
        return False

    print("VALID")
    return True


if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else '/app/configs/pipeline.json'
    sys.exit(0 if validate(path) else 1)
'''

with open('/app/validate_pipeline.py', 'w') as f:
    f.write(validator_code)
print("Created validate_pipeline.py")

print("\nAll fixes applied successfully.")
