"""
Spatial transform utilities for 3D medical images.

This module provides functions for manipulating 3D medical images
in NIfTI-style coordinate systems. All functions work with:
- 3D numpy arrays representing volumetric data
- 4x4 affine matrices mapping voxel (i,j,k) to world (x,y,z) coordinates:
  [x,y,z,1]^T = affine @ [i,j,k,1]^T

Axis code conventions (NIfTI standard):
  R = Right  (+x direction)    L = Left     (-x direction)
  A = Anterior (+y direction)  P = Posterior (-y direction)
  S = Superior (+z direction)  I = Inferior  (-z direction)
"""

import numpy as np
from scipy.ndimage import map_coordinates


def extract_spacing(affine):
    """Extract voxel spacing (mm) from a 4x4 affine matrix.

    Spacing is the magnitude of each column vector of the 3x3
    rotation/scaling submatrix.

    Parameters:
        affine: 4x4 numpy array

    Returns:
        1D array of 3 spacing values
    """
    return np.sum(np.abs(affine[:3, :3]), axis=0)


def extract_direction(affine):
    """Extract 3x3 direction cosine matrix from affine.

    The direction matrix is the rotation/scaling submatrix with each
    column normalized to unit length.
    """
    spacing = extract_spacing(affine)
    return affine[:3, :3] / spacing[None, :]


def extract_origin(affine):
    """Extract world coordinate origin (translation) from affine."""
    return affine[:3, 3].copy()


def build_affine(spacing, direction, origin):
    """Construct a 4x4 affine matrix from components.

    Parameters:
        spacing: array of 3 voxel spacings
        direction: 3x3 direction cosine matrix
        origin: array of 3 world coordinate offsets
    """
    spacing = np.asarray(spacing, dtype=float)
    direction = np.asarray(direction, dtype=float)
    origin = np.asarray(origin, dtype=float)
    affine = np.eye(4)
    affine[:3, :3] = direction * spacing[None, :]
    affine[:3, 3] = origin
    return affine


def get_axcodes(affine):
    """Determine axis orientation codes from affine matrix.

    Returns a 3-character string (e.g., 'RAS', 'LPS') indicating the
    anatomical direction each voxel axis most closely aligns with.

    NIfTI convention:
      Positive x -> R (Right)    Negative x -> L (Left)
      Positive y -> A (Anterior) Negative y -> P (Posterior)
      Positive z -> S (Superior) Negative z -> I (Inferior)
    """
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
    """Resample volume from source to target coordinate system.

    Uses inverse mapping: for each voxel in the target grid, computes
    its world coordinates via target_affine, maps to source voxel
    coordinates via inv(src_affine), and interpolates.

    Parameters:
        data: 3D numpy array
        src_affine: 4x4 affine for the source data
        target_affine: 4x4 affine for the target grid
        target_shape: tuple of 3 ints for the output shape
        order: interpolation order (0=nearest, 1=trilinear)

    Returns:
        3D numpy array of shape target_shape
    """
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
    """Resample volume to a new voxel spacing.

    Preserves the world coordinate origin and orientation direction.
    Output shape is computed to cover the same physical extent.

    Parameters:
        data: 3D numpy array
        src_affine: 4x4 affine for the input data
        new_spacing: array of 3 target spacings in mm
        order: interpolation order

    Returns:
        (resampled_data, new_affine) tuple
    """
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
    """Reorient volume to target axis codes.

    Performs axis permutation and/or flipping as needed. This is a pure
    data rearrangement (no interpolation). Updates the affine matrix so
    that the world coordinate mapping is preserved.

    Parameters:
        data: 3D numpy array
        src_affine: 4x4 affine for the input data
        target_codes: 3-character string, e.g. 'LPS', 'SAR'

    Returns:
        (reoriented_data, new_affine) tuple
    """
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

    # Build voxel-space mapping matrix: new_voxel -> old_voxel
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
    """Compose a sequence of 4x4 affine transforms.

    Transforms are applied left-to-right: the first transform in the list
    is applied first. Result: affine_list[-1] @ ... @ affine_list[1] @ affine_list[0].

    Parameters:
        affine_list: list of 4x4 numpy arrays

    Returns:
        4x4 numpy array
    """
    result = np.eye(4)
    for aff in affine_list:
        result = aff @ result
    return result


def invert_resample(resampled, resampled_affine, orig_shape, orig_affine, order=1):
    """Recover original volume from a resampled version.

    Given a resampled volume with its affine, plus the original shape and
    affine, resamples back to the original coordinate system.

    Parameters:
        resampled: 3D numpy array (the resampled data)
        resampled_affine: 4x4 affine for the resampled data
        orig_shape: tuple of 3 ints (original volume shape)
        orig_affine: 4x4 affine for the original volume
        order: interpolation order

    Returns:
        3D numpy array of shape orig_shape
    """
    return resample(resampled, orig_affine, resampled_affine, orig_shape, order=order)


def crop_to_roi(data, affine, roi_center_world, roi_size_world):
    """Extract a sub-volume from a world-coordinate region of interest.

    The ROI is an axis-aligned box in world space defined by its center
    point and full extent along each world axis. The function computes
    the tightest axis-aligned bounding box in voxel space that fully
    contains the world-space ROI, clips it to valid array bounds, and
    extracts the sub-volume. The returned affine maps new voxel (0,0,0)
    to the world coordinate of the extracted region's first voxel.

    Must handle oblique affine matrices where the world-space ROI box
    is not axis-aligned in voxel space.

    Parameters:
        data: 3D numpy array
        affine: 4x4 affine matrix
        roi_center_world: array of 3 world coordinates for ROI center
        roi_size_world: array of 3 physical extents in mm (full size per axis)

    Returns:
        (cropped_data, cropped_affine) tuple
    """
    raise NotImplementedError("crop_to_roi not yet implemented")


def register_landmarks(src_landmarks, tgt_landmarks):
    """Compute optimal rigid-body transform from corresponding landmarks.

    Given N >= 3 pairs of corresponding 3D points in world coordinates,
    finds the rotation R and translation t that minimizes the sum of
    squared distances: sum_i || R @ src_i + t - tgt_i ||^2

    The transform must be a proper rotation (det(R) = +1), not a
    reflection.

    Parameters:
        src_landmarks: Nx3 array of source points in world coordinates
        tgt_landmarks: Nx3 array of corresponding target points

    Returns:
        4x4 affine matrix mapping source to target coordinates
    """
    raise NotImplementedError("register_landmarks not yet implemented")


def evaluate_alignment(data1, affine1, data2, affine2, metric='ncc'):
    """Evaluate spatial alignment quality between two volumes.

    Resamples data2 into data1's coordinate space using data1's affine
    and shape as the reference frame. Computes the specified metric
    between data1 and the resampled data2.

    Supported metrics:
        'ncc': Normalized cross-correlation. Returns a value in [-1, 1]
               where 1.0 means perfect positive correlation.
               Formula: mean((a - mean(a)) * (b - mean(b))) / (std(a) * std(b))
        'mse': Mean squared error. Returns a non-negative value where
               0.0 means identical volumes.

    Parameters:
        data1: 3D numpy array (reference volume)
        affine1: 4x4 affine for data1
        data2: 3D numpy array (volume to evaluate)
        affine2: 4x4 affine for data2
        metric: 'ncc' or 'mse'

    Returns:
        float metric value
    """
    raise NotImplementedError("evaluate_alignment not yet implemented")
