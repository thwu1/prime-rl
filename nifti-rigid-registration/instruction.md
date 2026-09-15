Three synthetic patient volumes in `/app/data/` were derived from a reference
phantom by applying unknown rigid body transformations (rotation + translation)
in world coordinates. Recover the transformation parameters for each patient
and resample the patient volumes back to the reference coordinate space.

The file `/app/data/manifest.json` describes the transform convention,
coordinate system, and required output format.

## Required outputs

### `/app/output/registration_results.json`

A JSON object with keys `patient_1`, `patient_2`, `patient_3`. Each key maps
to an object containing a `transform_4x4` field — a 4x4 nested list
(row-major) representing the recovered rigid body transformation matrix.
Example structure:

```json
{
  "patient_1": {"transform_4x4": [[...], [...], [...], [...]]},
  "patient_2": {"transform_4x4": [[...], [...], [...], [...]]},
  "patient_3": {"transform_4x4": [[...], [...], [...], [...]]}
}
```

Each `transform_4x4` must be a valid 4x4 homogeneous matrix. Both the
forward transform (reference→patient) and its inverse are accepted — the
evaluation checks whichever convention yields the better match.

### `/app/output/resampled_1.nii.gz`, `/app/output/resampled_2.nii.gz`, `/app/output/resampled_3.nii.gz`

Each patient volume resampled onto the reference voxel grid. These must:

- Have the same shape as `/app/data/reference.nii.gz`
- Have an affine matrix matching the reference affine (to 2 decimal places)
- Achieve a normalised cross-correlation (NCC / Pearson correlation) above
  **0.93** against the reference volume

## Accuracy requirements

For each patient, the recovered transform must satisfy:

- **Rotation error** < 2.0 degrees (geodesic distance between 3x3 rotation
  matrices)
- **Translation error** < 2.5 mm (L2 norm of translation vector difference)

Pre-installed: `numpy`, `scipy`, `nibabel`.