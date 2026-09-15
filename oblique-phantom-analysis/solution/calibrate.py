#!/usr/bin/env python3

"""
Calibration Phantom Quality Assessment Tool

Detects fiducial markers in a 3D calibration phantom, matches them to
their ideal grid positions, estimates polynomial geometric distortion,
measures SNR, and evaluates quality against acceptance criteria.
"""

import json
import math
import numpy as np
import itk


def main():
    # ------------------------------------------------------------------
    # Load specification
    # ------------------------------------------------------------------
    with open("/app/calibration_spec.json") as f:
        spec = json.load(f)

    grid = spec["grid"]
    img_spec = spec["image"]
    criteria = spec["quality_criteria"]

    # ------------------------------------------------------------------
    # Load phantom image
    # ------------------------------------------------------------------
    image = itk.imread("/app/phantom.mha")
    arr = itk.array_from_image(image)  # shape (nz, ny, nx)

    spacing = list(image.GetSpacing())
    origin = list(image.GetOrigin())
    size = list(image.GetLargestPossibleRegion().GetSize())

    # ------------------------------------------------------------------
    # Step 1: Detect markers via thresholding + connected components
    # ------------------------------------------------------------------
    bg_int = grid["background_intensity"]
    marker_int = grid["marker_intensity"]
    threshold = (bg_int + marker_int) / 2.0

    binary = (arr > threshold).astype(np.uint8)

    # Connected component labeling via ITK
    binary_img = itk.image_from_array(binary)
    binary_img.SetSpacing(spacing)
    binary_img.SetOrigin(origin)

    UCType = itk.Image[itk.UC, 3]
    USType = itk.Image[itk.US, 3]

    cc = itk.ConnectedComponentImageFilter[UCType, USType].New()
    cc.SetInput(binary_img)
    cc.Update()
    labels = cc.GetOutput()
    labels_arr = itk.array_from_image(labels)

    label_vals = sorted(set(labels_arr.flat) - {0})

    # Compute centroids for each component, filtering small components (noise)
    min_voxels = 20  # a 3mm-radius sphere has ~113 voxels at 1mm spacing
    detected_centroids = []

    for lv in label_vals:
        component_mask = labels_arr == lv
        n_voxels = int(component_mask.sum())
        if n_voxels < min_voxels:
            continue

        # Get voxel indices: argwhere returns (N, 3) in [z, y, x] order
        indices = np.argwhere(component_mask)
        ijk = indices[:, ::-1].astype(np.float64)  # reverse to [x, y, z]

        # Convert to physical coordinates: physical = origin + index * spacing
        physical = np.array(origin) + ijk * np.array(spacing)
        centroid = physical.mean(axis=0)
        detected_centroids.append(centroid)

    # ------------------------------------------------------------------
    # Step 2: Generate ideal grid positions
    # ------------------------------------------------------------------
    ideal_positions = []
    grid_ids = []
    for i in range(grid["layout"][0]):
        for j in range(grid["layout"][1]):
            for k in range(grid["layout"][2]):
                pos = [
                    grid["origin_mm"][0] + i * grid["spacing_mm"][0],
                    grid["origin_mm"][1] + j * grid["spacing_mm"][1],
                    grid["origin_mm"][2] + k * grid["spacing_mm"][2],
                ]
                ideal_positions.append(pos)
                grid_ids.append([i, j, k])

    ideal_arr = np.array(ideal_positions, dtype=np.float64)

    # ------------------------------------------------------------------
    # Step 3: Match detected centroids to ideal positions (nearest neighbour)
    # ------------------------------------------------------------------
    # With distortion << marker spacing, nearest-neighbour is unambiguous.
    # Track used ideal indices to enforce uniqueness.
    used_ideal = set()
    matches = []  # list of (detected_idx, ideal_idx)

    # Sort detected by distance to nearest ideal for greedy assignment
    det_ideal_dists = []
    for di, dc in enumerate(detected_centroids):
        dists = np.linalg.norm(ideal_arr - dc, axis=1)
        det_ideal_dists.append((dists.min(), di, dists.argmin()))

    det_ideal_dists.sort()

    for _, di, best_ii in det_ideal_dists:
        if best_ii not in used_ideal:
            matches.append((di, best_ii))
            used_ideal.add(best_ii)
        else:
            # Fallback: find next nearest unused ideal
            dc = detected_centroids[di]
            dists = np.linalg.norm(ideal_arr - dc, axis=1)
            for rank in np.argsort(dists):
                if rank not in used_ideal:
                    matches.append((di, int(rank)))
                    used_ideal.add(int(rank))
                    break

    # ------------------------------------------------------------------
    # Step 4: Build marker result records
    # ------------------------------------------------------------------
    markers = []
    for di, ii in matches:
        detected = detected_centroids[di]
        ideal = ideal_arr[ii]
        displacement = detected - ideal
        magnitude = float(np.linalg.norm(displacement))
        markers.append({
            "grid_id": grid_ids[ii],
            "ideal_position_mm": ideal.tolist(),
            "detected_position_mm": detected.tolist(),
            "displacement_mm": displacement.tolist(),
            "displacement_magnitude_mm": magnitude,
        })

    markers.sort(key=lambda m: (m["grid_id"][0], m["grid_id"][1], m["grid_id"][2]))

    # ------------------------------------------------------------------
    # Step 5: Geometric error statistics
    # ------------------------------------------------------------------
    magnitudes = np.array([m["displacement_magnitude_mm"] for m in markers])
    geo_errors = {
        "max_mm": float(magnitudes.max()),
        "mean_mm": float(magnitudes.mean()),
        "rms_mm": float(np.sqrt((magnitudes**2).mean())),
    }

    # ------------------------------------------------------------------
    # Step 6: Fit 2nd-order polynomial distortion model
    # ------------------------------------------------------------------
    det_arr = np.array([m["detected_position_mm"] for m in markers])
    ideal_matched = np.array([m["ideal_position_mm"] for m in markers])
    displacements = det_arr - ideal_matched

    x, y, z = ideal_matched[:, 0], ideal_matched[:, 1], ideal_matched[:, 2]
    design = np.column_stack([x**2, y**2, z**2, x * y, x * z, y * z])

    coeffs_x, _, _, _ = np.linalg.lstsq(design, displacements[:, 0], rcond=None)
    coeffs_y, _, _, _ = np.linalg.lstsq(design, displacements[:, 1], rcond=None)
    coeffs_z, _, _, _ = np.linalg.lstsq(design, displacements[:, 2], rcond=None)

    # Compute fit residuals
    pred = np.column_stack([
        design @ coeffs_x,
        design @ coeffs_y,
        design @ coeffs_z,
    ])
    residuals = displacements - pred
    fit_residual_rms = float(np.sqrt((residuals**2).mean()))

    # ------------------------------------------------------------------
    # Step 7: Measure SNR
    # ------------------------------------------------------------------
    marker_mask = arr > threshold
    bg_mask = arr <= threshold

    mean_marker = float(arr[marker_mask].mean())
    mean_bg = float(arr[bg_mask].mean())
    std_bg = float(arr[bg_mask].std())

    snr_db = 20.0 * math.log10((mean_marker - mean_bg) / std_bg)

    # ------------------------------------------------------------------
    # Step 8: Quality assessment
    # ------------------------------------------------------------------
    quality = {
        "detection_pass": len(markers) >= criteria["min_detected_markers"],
        "geometric_pass": (
            geo_errors["max_mm"] <= criteria["max_geometric_error_mm"]
            and geo_errors["mean_mm"] <= criteria["mean_geometric_error_mm"]
        ),
        "snr_pass": snr_db >= criteria["min_snr_db"],
    }
    quality["overall"] = (
        "PASS" if all([quality["detection_pass"],
                       quality["geometric_pass"],
                       quality["snr_pass"]])
        else "FAIL"
    )

    # ------------------------------------------------------------------
    # Step 9: Write report
    # ------------------------------------------------------------------
    report = {
        "detected_markers": markers,
        "num_detected": len(markers),
        "geometric_errors": geo_errors,
        "distortion_model": {
            "coefficients_x": coeffs_x.tolist(),
            "coefficients_y": coeffs_y.tolist(),
            "coefficients_z": coeffs_z.tolist(),
            "fit_residual_rms_mm": fit_residual_rms,
        },
        "snr_db": snr_db,
        "quality_assessment": quality,
    }

    with open("/app/calibration_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"Detected {len(markers)} markers")
    print(f"Geometric errors: max={geo_errors['max_mm']:.3f}mm, "
          f"mean={geo_errors['mean_mm']:.3f}mm, rms={geo_errors['rms_mm']:.3f}mm")
    print(f"SNR: {snr_db:.1f} dB")
    print(f"Quality: {quality['overall']}")


if __name__ == "__main__":
    main()
