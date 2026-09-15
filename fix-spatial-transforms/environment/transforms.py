"""Spatial transform utilities for 3D medical images using NIfTI-style affine matrices."""

import numpy as np
from scipy.ndimage import map_coordinates


def extract_spacing(affine):
    """Extract voxel spacing from a 4x4 affine matrix."""
    return np.sum(np.abs(affine[:3, :3]), axis=0)


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
            codes += axis_labels[dominant_axis][1]
        else:
            codes += axis_labels[dominant_axis][0]
    return codes


def resample(data, src_affine, target_affine, target_shape, order=1):
    """Resample volume from source to target coordinate system."""
    grid = np.meshgrid(
        np.arange(target_shape[0]),
        np.arange(target_shape[1]),
        np.arange(target_shape[2]),
        indexing='xy'
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
    new_shape = np.floor(src_shape * src_spacing / new_spacing).astype(int)
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
    return resample(resampled, orig_affine, resampled_affine, orig_shape, order=order)


def register_landmarks(src_landmarks, tgt_landmarks):
    """Compute rigid-body registration from paired 3D landmarks."""
    raise NotImplementedError("register_landmarks not implemented")


def evaluate_alignment(data1, affine1, data2, affine2, metric='ncc'):
    """Evaluate alignment quality between two volumes."""
    raise NotImplementedError("evaluate_alignment not implemented")
