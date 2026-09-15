
"""
Solution: 3D medical phantom volume analysis pipeline.

Uses SimpleITK for image I/O, segmentation, and physical-space measurements.
SimpleITK's label shape statistics automatically account for spacing, origin,
and direction cosine matrix when computing centroids and other spatial metrics.
"""

import json

import numpy as np
import SimpleITK as sitk


def main():
    # ── Read phantom with full spatial metadata ──────────────────────────
    image = sitk.ReadImage("/app/phantom.mha")
    print(f"Image size:      {image.GetSize()}")
    print(f"Spacing:         {image.GetSpacing()}")
    print(f"Origin:          {image.GetOrigin()}")
    print(f"Direction:       {image.GetDirection()}")

    # ── Preprocessing: median filter for noise reduction ─────────────────
    # Use small radius to preserve structure boundaries
    smoothed = sitk.Median(image, [1, 1, 1])

    # ── Segmentation: Otsu thresholding ──────────────────────────────────
    otsu_filter = sitk.OtsuThresholdImageFilter()
    otsu_filter.SetInsideValue(0)
    otsu_filter.SetOutsideValue(1)
    binary = otsu_filter.Execute(smoothed)
    threshold = otsu_filter.GetThreshold()
    print(f"Otsu threshold:  {threshold:.1f}")

    # Verify that foreground (1) has higher intensity than background (0)
    arr_bin = sitk.GetArrayFromImage(binary)
    arr_img = sitk.GetArrayFromImage(image)
    fg_mean = float(arr_img[arr_bin == 1].mean()) if np.any(arr_bin == 1) else 0
    bg_mean = float(arr_img[arr_bin == 0].mean()) if np.any(arr_bin == 0) else 0
    print(f"FG mean: {fg_mean:.1f}, BG mean: {bg_mean:.1f}")

    if fg_mean < bg_mean:
        # Invert if Otsu convention is opposite
        binary = sitk.InvertIntensity(binary, maximum=1)
        print("Inverted binary mask (foreground was low-intensity)")

    # ── Connected component labeling ─────────────────────────────────────
    binary_uc = sitk.Cast(binary, sitk.sitkUInt8)
    cc = sitk.ConnectedComponent(binary_uc)

    # Relabel by size (largest component = label 1)
    # Compute minimum voxel count from 30 mm³ volume threshold
    voxel_volume = float(np.prod(image.GetSpacing()))
    min_voxels = max(1, int(30.0 / voxel_volume))
    relabeled = sitk.RelabelComponent(cc, minimumObjectSize=min_voxels)

    # ── Shape statistics (volume, centroid, surface area) ────────────────
    shape_stats = sitk.LabelShapeStatisticsImageFilter()
    shape_stats.Execute(relabeled)

    # ── Intensity statistics (mean intensity from original image) ────────
    intensity_stats = sitk.LabelStatisticsImageFilter()
    intensity_stats.Execute(image, relabeled)

    # ── Collect measurements ─────────────────────────────────────────────
    structures = []
    for label in shape_stats.GetLabels():
        if label == 0:
            continue

        volume_mm3 = shape_stats.GetPhysicalSize(label)
        if volume_mm3 < 30.0:
            continue

        centroid = shape_stats.GetCentroid(label)
        surface_area = shape_stats.GetPerimeter(label)
        mean_int = intensity_stats.GetMean(label)

        # Sphericity: psi = (pi^(1/3) * (6V)^(2/3)) / A
        if surface_area > 0:
            sphericity = (np.pi ** (1.0 / 3.0) * (6.0 * volume_mm3) ** (2.0 / 3.0)) / surface_area
        else:
            sphericity = 0.0

        structures.append({
            "label": int(label),
            "volume_mm3": float(volume_mm3),
            "centroid_mm": [float(centroid[0]), float(centroid[1]), float(centroid[2])],
            "mean_intensity": float(mean_int),
            "sphericity": float(sphericity),
        })

    # Sort by descending volume
    structures.sort(key=lambda s: -s["volume_mm3"])

    # Reassign labels after sorting
    for i, s in enumerate(structures):
        s["label"] = i + 1

    report = {
        "num_structures": len(structures),
        "structures": structures,
    }

    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nReport written to /app/report.json")
    print(f"Detected {len(structures)} structures:")
    for s in structures:
        print(f"  Label {s['label']}: V={s['volume_mm3']:.1f} mm³, "
              f"centroid={[round(c, 1) for c in s['centroid_mm']]}, "
              f"intensity={s['mean_intensity']:.1f}, "
              f"sphericity={s['sphericity']:.3f}")


if __name__ == "__main__":
    main()
