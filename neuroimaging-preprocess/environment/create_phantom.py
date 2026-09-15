#!/usr/bin/env python3
"""Create a synthetic brain phantom with B1-bias-field artifact and oblique orientation."""

import os

import nibabel as nib
import numpy as np
from scipy.ndimage import gaussian_filter


def generate_bias_field(shape, order, coefficients):
    """Generate a smooth multiplicative bias field from polynomial basis.

    Models MRI B1-field inhomogeneity as exp(sum of polynomial terms),
    following the approach described in Van Leemput et al., 1999.
    """
    coords = [np.linspace(-1, 1, s) for s in shape]
    meshes = np.meshgrid(*coords, indexing='ij')

    log_bias = np.zeros(shape, dtype=np.float64)
    idx = 0
    for x_order in range(order + 1):
        for y_order in range(order + 1 - x_order):
            for z_order in range(order + 1 - (x_order + y_order)):
                log_bias += coefficients[idx] * (
                    meshes[0] ** x_order
                    * meshes[1] ** y_order
                    * meshes[2] ** z_order
                )
                idx += 1

    return np.exp(log_bias).astype(np.float32)


def main():
    os.makedirs('/app/data', exist_ok=True)
    os.makedirs('/app/output', exist_ok=True)

    shape = (160, 192, 128)
    spacing = np.array([0.8, 1.2, 1.0])
    center_voxel = np.array(shape, dtype=np.float64) / 2.0

    # --- Oblique affine: compound rotation around S (12 deg) and R (7 deg) ---
    theta_s = np.radians(12)
    theta_r = np.radians(7)

    Rs = np.array([
        [np.cos(theta_s), -np.sin(theta_s), 0],
        [np.sin(theta_s),  np.cos(theta_s), 0],
        [0, 0, 1],
    ])
    Rr = np.array([
        [1, 0, 0],
        [0, np.cos(theta_r), -np.sin(theta_r)],
        [0, np.sin(theta_r),  np.cos(theta_r)],
    ])
    R = Rs @ Rr

    # LAS+ base: voxel i -> -R, j -> +A, k -> +S
    las_base = np.diag([-spacing[0], spacing[1], spacing[2]])
    direction = R @ las_base

    affine = np.eye(4)
    affine[:3, :3] = direction
    affine[:3, 3] = -direction @ center_voxel

    # --- Coordinate grids (voxel-centred) ---
    ii, jj, kk = np.mgrid[:shape[0], :shape[1], :shape[2]]
    ci = ii.astype(np.float64) - center_voxel[0]
    cj = jj.astype(np.float64) - center_voxel[1]
    ck = kk.astype(np.float64) - center_voxel[2]

    # --- Tissue geometry ---
    brain_r = np.array([55.0, 68.0, 52.0])
    brain_d = np.sqrt(
        (ci / brain_r[0]) ** 2 + (cj / brain_r[1]) ** 2 + (ck / brain_r[2]) ** 2
    )
    brain_mask = brain_d < 1.0

    wm_r = np.array([32.0, 40.0, 30.0])
    wm_d = np.sqrt(
        (ci / wm_r[0]) ** 2 + (cj / wm_r[1]) ** 2 + (ck / wm_r[2]) ** 2
    )
    wm_mask = wm_d < 1.0

    csf_shell = brain_mask & (brain_d > 0.90)
    gm_mask = brain_mask & ~wm_mask & ~csf_shell

    # Lateral ventricles (CSF-filled cavities inside WM)
    lv_c, rv_c = np.array([12.0, 8.0, 4.0]), np.array([-12.0, 8.0, 4.0])
    vent_r = np.array([6.0, 16.0, 20.0])
    lv_d = np.sqrt(
        ((ci - lv_c[0]) / vent_r[0]) ** 2
        + ((cj - lv_c[1]) / vent_r[1]) ** 2
        + ((ck - lv_c[2]) / vent_r[2]) ** 2
    )
    rv_d = np.sqrt(
        ((ci - rv_c[0]) / vent_r[0]) ** 2
        + ((cj - rv_c[1]) / vent_r[1]) ** 2
        + ((ck - rv_c[2]) / vent_r[2]) ** 2
    )
    vent_mask = (lv_d < 1.0) | (rv_d < 1.0)

    # Ventricles carve into WM/GM
    wm_mask = wm_mask & ~vent_mask
    gm_mask = gm_mask & ~vent_mask
    csf_mask = csf_shell | (vent_mask & brain_mask)

    # --- Base intensities ---
    data = np.zeros(shape, dtype=np.float64)
    data[csf_mask] = 300.0
    data[gm_mask] = 700.0
    data[wm_mask] = 1000.0

    # Smooth intra-tissue texture
    rng1 = np.random.RandomState(42)
    texture = gaussian_filter(rng1.randn(*shape) * 20.0, sigma=5.0)
    data[brain_mask] += texture[brain_mask]

    # --- Multiplicative bias field (polynomial order 2, 10 coefficients) ---
    # Enumeration: (x,y,z) orders =
    #   (0,0,0) (0,0,1) (0,0,2) (0,1,0) (0,1,1) (0,2,0)
    #   (1,0,0) (1,0,1) (1,1,0) (2,0,0)
    bias_coefficients = [
        0.00,   # 1
        0.18,   # z
       -0.07,   # z^2
       -0.12,   # y
        0.04,   # yz
       -0.06,   # y^2
        0.15,   # x
        0.03,   # xz
       -0.05,   # xy
       -0.09,   # x^2
    ]
    bias_field = generate_bias_field(shape, 2, bias_coefficients)
    data *= bias_field

    # Additive noise (post-bias, as in real MRI acquisition)
    rng2 = np.random.RandomState(123)
    data += rng2.randn(*shape) * 15.0
    data = np.clip(data, 0.0, None).astype(np.float32)

    # --- Label map ---
    labels = np.zeros(shape, dtype=np.int16)
    labels[csf_mask] = 1
    labels[gm_mask] = 2
    labels[wm_mask] = 3

    # --- Save ---
    nib.save(nib.Nifti1Image(data, affine), '/app/data/phantom.nii.gz')
    nib.save(nib.Nifti1Image(labels, affine), '/app/data/labels.nii.gz')

    ornt = ''.join(nib.orientations.aff2axcodes(affine))
    bb = bias_field[brain_mask]
    print(f"Phantom: shape={shape}, spacing={spacing.tolist()}, orientation={ornt}")
    print(f"Tissues — CSF: {int(csf_mask.sum())}, GM: {int(gm_mask.sum())}, WM: {int(wm_mask.sum())}")
    print(f"Bias field over brain: [{bb.min():.3f}, {bb.max():.3f}]")


if __name__ == '__main__':
    main()
