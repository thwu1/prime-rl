A synthetic 3D medical phantom volume is at `/app/phantom.mha` in MetaImage format. It contains multiple high-intensity ellipsoidal structures embedded in a noisy background. The volume has anisotropic voxel spacing and a non-trivial spatial coordinate system: non-zero origin and a non-identity direction cosine matrix (rotation about one axis).

Create `/app/analyze.py` that reads the phantom with all spatial metadata (spacing, origin, direction cosines), segments the high-intensity structures from the noisy background, labels each structure individually via connected component analysis, discards components with physical volume below 30 mm³, and computes per-structure physical-space measurements.

Required measurements for each structure:
- **volume_mm3**: physical volume in mm³, accounting for anisotropic voxel spacing
- **centroid_mm**: centroid position `[x, y, z]` in world coordinates (mm), correctly applying spacing, origin, AND the direction cosine matrix
- **mean_intensity**: mean voxel intensity from the original (unsmoothed) image within the structure
- **sphericity**: ψ = (π^(1/3) · (6V)^(2/3)) / A, where V is volume in mm³ and A is surface area in mm²

Write results to `/app/report.json` sorted by descending volume:

```json
{
  "num_structures": 6,
  "structures": [
    {
      "label": 1,
      "volume_mm3": 850.0,
      "centroid_mm": [29.2, 4.0, 44.0],
      "mean_intensity": 180.2,
      "sphericity": 0.85
    }
  ]
}
```

Values shown above are illustrative, not exact answers.