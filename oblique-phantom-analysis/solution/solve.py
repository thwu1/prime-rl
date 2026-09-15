#!/usr/bin/env python3

"""
Corrected Phantom Analysis Pipeline

Fixes:
1. Direction matrix: Rz @ Rx (not Rx @ Rz)
2. Sphere embedding: uses full affine with direction matrix
"""

import json
import math
import numpy as np
import itk


def build_direction_matrix(angles):
    """Build direction cosine matrix from Euler rotation angles.
    Convention: Rz(z_rotation) @ Rx(x_tilt) — intrinsic z-then-x."""
    tz = math.radians(angles["z_rotation"])
    tx = math.radians(angles["x_tilt"])
    cz, sz = math.cos(tz), math.sin(tz)
    cx, sx = math.cos(tx), math.sin(tx)

    Rx = np.array([
        [1,  0,   0],
        [0,  cx, -sx],
        [0,  sx,  cx],
    ], dtype=np.float64)

    Rz = np.array([
        [cz, -sz, 0],
        [sz,  cz, 0],
        [0,   0,  1],
    ], dtype=np.float64)

    # FIX 1: correct rotation order — Rz @ Rx, not Rx @ Rz
    return Rz @ Rx


def main():
    with open("/app/config.json") as f:
        config = json.load(f)

    size = config["image_size"]
    spacing = config["spacing_mm"]
    origin = config["origin_mm"]
    structures = config["structures"]
    bg = float(config["background_intensity"])
    sigma = float(config["smoothing_sigma_mm"])

    nx, ny, nz = size
    sp = np.array(spacing, dtype=np.float64)
    org = np.array(origin, dtype=np.float64)

    direction = build_direction_matrix(config["direction_angles_deg"])
    DS = direction @ np.diag(sp)

    # ---- Build voxel array (NumPy axis order: z, y, x) ----
    arr = np.full((nz, ny, nx), bg, dtype=np.float32)

    ii, jj, kk = np.meshgrid(
        np.arange(nx, dtype=np.float64),
        np.arange(ny, dtype=np.float64),
        np.arange(nz, dtype=np.float64),
        indexing="ij",
    )

    # FIX 2: use full affine mapping with direction matrix
    px = org[0] + DS[0, 0] * ii + DS[0, 1] * jj + DS[0, 2] * kk
    py = org[1] + DS[1, 0] * ii + DS[1, 1] * jj + DS[1, 2] * kk
    pz = org[2] + DS[2, 0] * ii + DS[2, 1] * jj + DS[2, 2] * kk

    for s in structures:
        scx, scy, scz = s["center_mm"]
        r = s["radius_mm"]
        intensity = float(s["intensity"])
        dist_sq = (px - scx) ** 2 + (py - scy) ** 2 + (pz - scz) ** 2
        mask = dist_sq <= r ** 2
        arr[mask.transpose(2, 1, 0)] = intensity

    # ---- Wrap as ITK image with spatial metadata ----
    image = itk.image_from_array(arr)
    image.SetSpacing(spacing)
    image.SetOrigin(origin)
    image.SetDirection(itk.matrix_from_array(direction))

    itk.imwrite(image, "/app/phantom.mha")

    # ---- Gaussian smoothing (sigma in physical mm) ----
    ImageType = type(image)
    smoother = itk.SmoothingRecursiveGaussianImageFilter[ImageType, ImageType].New()
    smoother.SetInput(image)
    smoother.SetSigma(sigma)
    smoother.Update()
    smoothed = smoother.GetOutput()

    # ---- Threshold segmentation ----
    UCType = itk.Image[itk.UC, 3]
    thr_val = (bg + float(structures[0]["intensity"])) / 2.0
    thresh = itk.BinaryThresholdImageFilter[ImageType, UCType].New()
    thresh.SetInput(smoothed)
    thresh.SetLowerThreshold(thr_val)
    thresh.SetUpperThreshold(float(structures[0]["intensity"]) * 2.0)
    thresh.SetInsideValue(1)
    thresh.SetOutsideValue(0)
    thresh.Update()
    binary = thresh.GetOutput()

    # ---- Connected component labeling ----
    USType = itk.Image[itk.US, 3]
    cc = itk.ConnectedComponentImageFilter[UCType, USType].New()
    cc.SetInput(binary)
    cc.Update()
    labels = cc.GetOutput()

    # ---- Measure structures ----
    labels_arr = itk.array_from_image(labels)  # (nz, ny, nx)
    label_vals = sorted(set(labels_arr.flat) - {0})

    voxel_vol = float(np.prod(sp))
    detected = []
    for lv in label_vals:
        component_mask = labels_arr == lv
        indices = np.argwhere(component_mask)
        ijk = indices[:, ::-1].astype(np.float64)
        coords = org + (DS @ ijk.T).T
        centroid = coords.mean(axis=0).tolist()
        volume = int(component_mask.sum()) * voxel_vol
        detected.append({
            "centroid_mm": centroid,
            "volume_mm3": volume,
        })

    # ---- Match each component to nearest ground-truth sphere ----
    for det in detected:
        best_dist, best_name = float("inf"), None
        for s in structures:
            d = math.sqrt(
                sum((a - b) ** 2 for a, b in zip(det["centroid_mm"], s["center_mm"]))
            )
            if d < best_dist:
                best_dist, best_name = d, s["name"]
        det["matched_name"] = best_name

    detected.sort(key=lambda d: d["matched_name"])

    results = {
        "image_metadata": {
            "size": size,
            "spacing_mm": spacing,
            "origin_mm": origin,
            "direction": direction.tolist(),
        },
        "num_structures": len(detected),
        "structures": detected,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Found {len(detected)} structures")
    for d in detected:
        print(f"  {d['matched_name']}: centroid={d['centroid_mm']}, "
              f"vol={d['volume_mm3']:.1f} mm3")


if __name__ == "__main__":
    main()
