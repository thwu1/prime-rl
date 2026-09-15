#!/usr/bin/env python3
"""Rigid-body registration of patient volumes to a reference phantom.

Multi-resolution strategy with global optimizer at coarsest level:
1. Downsample both volumes by 4x -- use differential_evolution (global).
2. Downsample by 2x -- refine with Powell.
3. Full resolution -- final refinement with Powell.

"""

import json
import os

import numpy as np
import nibabel as nib
from scipy.ndimage import affine_transform as scipy_affine_transform
from scipy.ndimage import zoom
from scipy.optimize import minimize, differential_evolution
from scipy.spatial.transform import Rotation


# -- helpers -----------------------------------------------------------------

def params_to_matrix(params):
    """Convert [rz, ry, rx, tx, ty, tz] (deg, mm) -> 4x4 homogeneous matrix."""
    R = Rotation.from_euler("ZYX", params[:3], degrees=True)
    T = np.eye(4)
    T[:3, :3] = R.as_matrix()
    T[:3, 3] = params[3:6]
    return T


def resample_patient(patient_data, affine, T, order=1):
    """Resample *patient_data* to reference space given transform T.

    T maps reference world coords -> patient world coords.
    For each reference-grid voxel u the corresponding patient voxel is
        v = (A_inv @ T @ A) @ u
    which is exactly the mapping scipy.ndimage.affine_transform needs
    (output[u] = input[M @ u + b]).
    """
    A_inv = np.linalg.inv(affine)
    M = A_inv @ T @ affine
    return scipy_affine_transform(
        patient_data, M[:3, :3], M[:3, 3],
        order=order, mode="constant", cval=0.0,
    ).astype(np.float32)


def mse_cost(params, ref_data, patient_data, affine):
    """Mean squared error between reference and resampled patient."""
    T = params_to_matrix(params)
    aligned = resample_patient(patient_data, affine, T, order=1)
    return float(np.mean((ref_data - aligned) ** 2))


def _downsample(data, factor):
    """Downsample volume by an integer factor."""
    return zoom(data, 1.0 / factor, order=1).astype(np.float32)


def _adjust_affine(affine, factor):
    """Adjust affine for downsampled grid (voxel spacing *= factor)."""
    aff = affine.copy()
    aff[:3, :3] *= factor
    return aff


def register(ref_data, patient_data, affine):
    """Multi-resolution rigid registration with global optimizer."""

    # -- Level 0: coarsest (4x downsampled) with differential_evolution ------
    ref_c = _downsample(ref_data, 4)
    pat_c = _downsample(patient_data, 4)
    aff_c = _adjust_affine(affine, 4)

    bounds = [(-45, 45), (-45, 45), (-45, 45),
              (-25, 25), (-25, 25), (-25, 25)]

    de_result = differential_evolution(
        mse_cost, bounds, args=(ref_c, pat_c, aff_c),
        seed=42, maxiter=400, tol=1e-9,
        mutation=(0.5, 1.5), recombination=0.9,
        popsize=20, polish=True,
    )
    best_x = de_result.x.copy()

    # -- Level 1: medium (2x downsampled) ------------------------------------
    ref_m = _downsample(ref_data, 2)
    pat_m = _downsample(patient_data, 2)
    aff_m = _adjust_affine(affine, 2)

    res = minimize(
        mse_cost, best_x, args=(ref_m, pat_m, aff_m),
        method="Powell",
        options={"maxiter": 2000, "ftol": 1e-12, "xtol": 1e-10},
    )

    # -- Level 2: full resolution --------------------------------------------
    result = minimize(
        mse_cost, res.x, args=(ref_data, patient_data, affine),
        method="Powell",
        options={"maxiter": 3000, "ftol": 1e-12, "xtol": 1e-10},
    )

    return params_to_matrix(result.x), result


# -- main --------------------------------------------------------------------

def main():
    os.makedirs("/app/output", exist_ok=True)

    ref_img = nib.load("/app/data/reference.nii.gz")
    ref_data = ref_img.get_fdata(dtype=np.float32)
    affine = ref_img.affine.copy()

    results = {}

    for i in range(1, 4):
        name = f"patient_{i}"
        print(f"[*] Registering {name} …", flush=True)

        patient_img = nib.load(f"/app/data/{name}.nii.gz")
        patient_data = patient_img.get_fdata(dtype=np.float32)

        T, opt = register(ref_data, patient_data, affine)
        print(f"    converged={opt.success}  nfev={opt.nfev}  "
              f"mse={opt.fun:.6e}  params={np.round(opt.x, 4).tolist()}")

        results[name] = {"transform_4x4": T.tolist()}

        # Final resample with cubic interpolation for quality
        aligned = resample_patient(patient_data, affine, T, order=3)
        nib.save(nib.Nifti1Image(aligned, affine),
                 f"/app/output/resampled_{i}.nii.gz")

    with open("/app/output/registration_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("[+] Done.", flush=True)


if __name__ == "__main__":
    main()
