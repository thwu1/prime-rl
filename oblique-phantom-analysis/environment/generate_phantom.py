#!/usr/bin/env python3

"""Generate a 3D calibration phantom with known polynomial geometric distortion.

This script is executed during Docker image build and then removed.
The distortion coefficients embedded here are NOT revealed to the agent.
"""

import json
import numpy as np
import itk


DISTORTION_COEFFS = {
    "x": [1.5e-3, -0.75e-3, 1.0e-3, -1.25e-3, 0.5e-3, -0.25e-3],
    "y": [-0.5e-3, 1.0e-3, -0.75e-3, 0.75e-3, -0.5e-3, 1.0e-3],
    "z": [0.25e-3, -0.5e-3, 1.5e-3, 0.5e-3, -0.75e-3, 0.25e-3],
}


def main():
    with open("/app/calibration_spec.json") as f:
        spec = json.load(f)

    grid = spec["grid"]
    img = spec["image"]

    # Generate ideal marker positions in physical coordinates (mm)
    ideal = []
    for i in range(grid["layout"][0]):
        for j in range(grid["layout"][1]):
            for k in range(grid["layout"][2]):
                ideal.append([
                    grid["origin_mm"][0] + i * grid["spacing_mm"][0],
                    grid["origin_mm"][1] + j * grid["spacing_mm"][1],
                    grid["origin_mm"][2] + k * grid["spacing_mm"][2],
                ])
    ideal = np.array(ideal, dtype=np.float64)

    # Apply 2nd-order polynomial distortion to marker positions
    x, y, z = ideal[:, 0], ideal[:, 1], ideal[:, 2]
    quad = np.column_stack([x**2, y**2, z**2, x * y, x * z, y * z])

    distorted = ideal.copy()
    for axis, key in enumerate(["x", "y", "z"]):
        distorted[:, axis] += quad @ np.array(DISTORTION_COEFFS[key])

    # Image parameters
    sz = img["size"]       # [nx, ny, nz]
    sp = img["spacing_mm"]  # [sx, sy, sz]
    org = img["origin_mm"]  # [ox, oy, oz]
    r = grid["marker_radius_mm"]
    marker_int = float(grid["marker_intensity"])
    bg_int = float(grid["background_intensity"])

    # Create 3D array in NumPy axis order (z, y, x)
    arr = np.full((sz[2], sz[1], sz[0]), bg_int, dtype=np.float32)

    ri = int(np.ceil(r / sp[0]))
    rj = int(np.ceil(r / sp[1]))
    rk = int(np.ceil(r / sp[2]))

    for dpos in distorted:
        # Continuous voxel coordinates of distorted marker center
        ci = (dpos[0] - org[0]) / sp[0]
        cj = (dpos[1] - org[1]) / sp[1]
        ck = (dpos[2] - org[2]) / sp[2]

        for di in range(-ri, ri + 1):
            for dj in range(-rj, rj + 1):
                for dk in range(-rk, rk + 1):
                    ii = int(round(ci)) + di
                    jj = int(round(cj)) + dj
                    kk = int(round(ck)) + dk
                    if 0 <= ii < sz[0] and 0 <= jj < sz[1] and 0 <= kk < sz[2]:
                        px = ii * sp[0] + org[0]
                        py = jj * sp[1] + org[1]
                        pz = kk * sp[2] + org[2]
                        d2 = (px - dpos[0])**2 + (py - dpos[1])**2 + (pz - dpos[2])**2
                        if d2 <= r**2:
                            arr[kk, jj, ii] = marker_int

    # Add deterministic Gaussian noise
    rng = np.random.RandomState(42)
    arr += rng.normal(0, spec["noise_sigma"], arr.shape).astype(np.float32)
    arr = np.clip(arr, 0, 65535).astype(np.float32)

    # Save as ITK MetaImage
    image = itk.image_from_array(arr)
    image.SetSpacing(sp)
    image.SetOrigin(org)
    itk.imwrite(image, "/app/phantom.mha")

    disp = np.linalg.norm(distorted - ideal, axis=1)
    print(f"Phantom generated: {len(ideal)} markers, "
          f"max_disp={disp.max():.3f}mm, mean_disp={disp.mean():.3f}mm, "
          f"rms_disp={np.sqrt((disp**2).mean()):.3f}mm")


if __name__ == "__main__":
    main()
