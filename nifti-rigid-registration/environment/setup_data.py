#!/usr/bin/env python3
"""Generate reference phantom and transformed patient volumes for registration task."""
import json
import numpy as np
import nibabel as nib
from scipy.ndimage import affine_transform
from scipy.spatial.transform import Rotation


def create_phantom(shape=(96, 112, 96)):
    """Create 3D phantom with multiple asymmetric ellipsoidal structures.

    The asymmetry ensures rigid registration has a unique solution.
    """
    phantom = np.zeros(shape, dtype=np.float32)
    ci = shape[0] / 2.0
    cj = shape[1] / 2.0
    ck = shape[2] / 2.0

    ii = np.arange(shape[0], dtype=np.float32)[:, None, None]
    jj = np.arange(shape[1], dtype=np.float32)[None, :, None]
    kk = np.arange(shape[2], dtype=np.float32)[None, None, :]

    # Each tuple: (center_offset, radii, intensity)
    structures = [
        ((0, 0, 0), (40, 48, 40), 0.4),
        ((0, 0, 0), (28, 32, 28), 0.8),
        ((12, -8, 3), (7, 9, 7), 1.0),
        ((-15, 12, 6), (5, 5, 14), 0.6),
        ((8, 18, -12), (11, 4, 4), 0.2),
        ((-10, -15, 18), (4, 7, 6), 0.9),
        ((22, 10, -8), (3, 3, 18), 0.5),
        ((-28, -22, -18), (8, 4, 6), 0.75),
    ]

    for (oi, oj, ok), (ri, rj, rk), intensity in structures:
        dist = (
            ((ii - (ci + oi)) / ri) ** 2
            + ((jj - (cj + oj)) / rj) ** 2
            + ((kk - (ck + ok)) / rk) ** 2
        )
        phantom[dist <= 1.0] = intensity

    return phantom


def make_affine(shape, spacing=(1.0, 1.0, 1.0)):
    """Create RAS+ affine centered so volume center maps to world origin."""
    affine = np.diag([spacing[0], spacing[1], spacing[2], 1.0])
    affine[0, 3] = -spacing[0] * (shape[0] - 1) / 2.0
    affine[1, 3] = -spacing[1] * (shape[1] - 1) / 2.0
    affine[2, 3] = -spacing[2] * (shape[2] - 1) / 2.0
    return affine


def make_rigid_transform(euler_zyx_deg, translation_mm):
    """4x4 rigid body transform from ZYX Euler angles (degrees) and translation (mm)."""
    R = Rotation.from_euler('ZYX', euler_zyx_deg, degrees=True)
    T = np.eye(4)
    T[:3, :3] = R.as_matrix()
    T[:3, 3] = translation_mm
    return T


def apply_transform_to_volume(ref_data, affine, T_ref_to_patient):
    """Generate a patient volume by transforming reference anatomy.

    T maps reference world coords -> patient world coords.
    patient[v] = ref[ (A_inv @ T_inv @ A) @ v ]
    """
    A_inv = np.linalg.inv(affine)
    T_inv = np.linalg.inv(T_ref_to_patient)
    M = A_inv @ T_inv @ affine
    patient = affine_transform(
        ref_data, M[:3, :3], M[:3, 3],
        order=3, mode='constant', cval=0.0,
    )
    return patient.astype(np.float32)


def main():
    shape = (96, 112, 96)
    phantom = create_phantom(shape)
    affine = make_affine(shape)

    ref_img = nib.Nifti1Image(phantom, affine)
    nib.save(ref_img, '/app/data/reference.nii.gz')

    # Ground-truth transforms (NOT exposed to the agent)
    transforms = [
        ([12.0, -8.0, 5.0], [4.0, -3.0, 6.0]),
        ([-5.0, 15.0, -10.0], [-7.0, 2.0, -4.0]),
        ([8.0, 3.0, -20.0], [10.0, 5.0, -8.0]),
    ]

    for i, (euler, trans) in enumerate(transforms, 1):
        T = make_rigid_transform(euler, trans)
        patient_data = apply_transform_to_volume(phantom, affine, T)
        patient_img = nib.Nifti1Image(patient_data, affine)
        nib.save(patient_img, f'/app/data/patient_{i}.nii.gz')

    manifest = {
        "task": "rigid_body_registration",
        "description": (
            "Three patient volumes were derived from a reference phantom by applying "
            "rigid body transformations (rotation + translation) in world coordinates. "
            "Recover the transformation parameters and resample each patient volume "
            "to the reference space."
        ),
        "reference": "/app/data/reference.nii.gz",
        "patients": [
            "/app/data/patient_1.nii.gz",
            "/app/data/patient_2.nii.gz",
            "/app/data/patient_3.nii.gz",
        ],
        "transform_convention": (
            "T is a 4x4 homogeneous matrix that maps points from reference world "
            "coordinates to patient world coordinates.  Given a point p_ref in "
            "reference space, the corresponding point in patient space is "
            "p_patient = T @ p_ref.  The coordinate system is RAS+ (NIfTI standard).  "
            "All volumes share the same voxel grid (identical affine in NIfTI headers).  "
            "The patient volumes contain the same anatomy as the reference, but the "
            "anatomy has been spatially transformed before sampling on the shared grid."
        ),
        "output": {
            "registration_results": "/app/output/registration_results.json",
            "resampled_volumes": [
                "/app/output/resampled_1.nii.gz",
                "/app/output/resampled_2.nii.gz",
                "/app/output/resampled_3.nii.gz",
            ],
        },
        "output_schema": {
            "registration_results.json": {
                "patient_1": {"transform_4x4": "4x4 nested list, row-major"},
                "patient_2": {"transform_4x4": "4x4 nested list, row-major"},
                "patient_3": {"transform_4x4": "4x4 nested list, row-major"},
            },
        },
    }

    with open('/app/data/manifest.json', 'w') as f:
        json.dump(manifest, f, indent=2)

    print("Data generation complete.")


if __name__ == '__main__':
    main()
