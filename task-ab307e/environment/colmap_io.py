"""
COLMAP text format I/O utilities.

Reads camera, image, and 3D point data in COLMAP's text format.
Reference: https://colmap.github.io/format.html

Quaternion conventions:
- COLMAP stores image rotations as quaternions in WXYZ (scalar-first) order: [qw, qx, qy, qz]
- This pipeline uses XYZW (scalar-last) order internally: [qx, qy, qz, qw]
- The conversion is handled during I/O
"""

# Adapted from VGGT COLMAP export utilities (facebookresearch/vggt)

import numpy as np
import os


def read_cameras_text(path):
    """Read cameras.txt in COLMAP text format.

    Supported camera models and their parameter ordering:
    - PINHOLE: fx, fy, cx, cy
    - SIMPLE_PINHOLE: f, cx, cy

    Args:
        path: path to cameras.txt

    Returns:
        dict mapping camera_id to dict with keys: model, width, height, intrinsic (3x3)
    """
    cameras = {}
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            camera_id = int(parts[0])
            model = parts[1]
            width = int(parts[2])
            height = int(parts[3])
            params = np.array([float(x) for x in parts[4:]])

            if model == 'PINHOLE':
                # PINHOLE params order: fx, fy, cx, cy
                fx, fy, cx, cy = params[0], params[1], params[2], params[3]
                intrinsic = np.array([
                    [fx,  0, cx],
                    [ 0, fy, cy],
                    [ 0,  0,  1]
                ], dtype=np.float64)
            elif model == 'SIMPLE_PINHOLE':
                f, cx, cy = params
                intrinsic = np.array([
                    [f, 0, cx],
                    [0, f, cy],
                    [0, 0,  1]
                ], dtype=np.float64)
            else:
                raise ValueError(f"Unsupported camera model: {model}")

            cameras[camera_id] = {
                'model': model,
                'width': width,
                'height': height,
                'intrinsic': intrinsic,
            }

    return cameras


def read_images_text(path):
    """Read images.txt in COLMAP text format.

    Each image occupies two lines:
    Line 1: IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME
    Line 2: POINTS2D[] as (X, Y, POINT3D_ID)

    COLMAP quaternions are in WXYZ (scalar-first) format.
    We convert to XYZW (scalar-last) for internal use.

    Args:
        path: path to images.txt

    Returns:
        dict mapping image_id to dict with keys:
            quat_xyzw (4,), translation (3,), camera_id, name
    """
    images = {}
    with open(path, 'r') as f:
        lines = [l.strip() for l in f if l.strip() and not l.strip().startswith('#')]

    # Process pairs of lines (image info + points2D)
    i = 0
    while i < len(lines):
        parts = lines[i].split()
        image_id = int(parts[0])

        # COLMAP stores: QW, QX, QY, QZ (WXYZ, scalar-first)
        qw = float(parts[1])
        qx = float(parts[2])
        qy = float(parts[3])
        qz = float(parts[4])
        tx, ty, tz = float(parts[5]), float(parts[6]), float(parts[7])
        camera_id = int(parts[8])
        name = parts[9]

        # Convert COLMAP WXYZ to pipeline XYZW convention
        quat_xyzw = np.array([qw, qx, qy, qz], dtype=np.float64)

        translation = np.array([tx, ty, tz], dtype=np.float64)

        images[image_id] = {
            'quat_xyzw': quat_xyzw,
            'translation': translation,
            'camera_id': camera_id,
            'name': name,
        }

        i += 2  # Skip the POINTS2D line

    return images


def read_points3d_text(path):
    """Read points3D.txt in COLMAP text format.

    Each line: POINT3D_ID, X, Y, Z, R, G, B, ERROR, TRACK[] as (IMAGE_ID, POINT2D_IDX)

    Args:
        path: path to points3D.txt

    Returns:
        dict mapping point3d_id to dict with keys: xyz (3,), rgb (3,), error (float)
    """
    points = {}
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            point_id = int(parts[0])
            xyz = np.array([float(parts[1]), float(parts[2]), float(parts[3])], dtype=np.float64)
            rgb = np.array([int(parts[4]), int(parts[5]), int(parts[6])], dtype=np.uint8)
            error = float(parts[7])

            points[point_id] = {
                'xyz': xyz,
                'rgb': rgb,
                'error': error,
            }

    return points


def load_scene(data_dir):
    """Load a complete scene from COLMAP text format files.

    Args:
        data_dir: directory containing cameras.txt, images.txt, points3D.txt

    Returns:
        cameras, images, points dicts
    """
    cameras = read_cameras_text(os.path.join(data_dir, 'cameras.txt'))
    images = read_images_text(os.path.join(data_dir, 'images.txt'))
    points = read_points3d_text(os.path.join(data_dir, 'points3D.txt'))
    return cameras, images, points


def build_extrinsic_from_quat_trans(quat_xyzw, translation):
    """Build a 3x4 extrinsic matrix from quaternion and translation.

    Args:
        quat_xyzw: (4,) quaternion in XYZW order (scalar-last)
        translation: (3,) translation vector

    Returns:
        (3, 4) extrinsic matrix [R|t]
    """
    from rotation_utils import quat_to_mat
    R = quat_to_mat(quat_xyzw[np.newaxis])[0]
    extrinsic = np.zeros((3, 4), dtype=np.float64)
    extrinsic[:3, :3] = R
    extrinsic[:3, 3] = translation
    return extrinsic
