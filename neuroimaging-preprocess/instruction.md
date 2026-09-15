A synthetic brain phantom at `/app/data/` (`phantom.nii.gz` with tissue segmentation `labels.nii.gz`) fails quality gates for a downstream neuroimaging analysis pipeline. The volume was acquired with non-standard oblique geometry (compound rotation, anisotropic spacing) and exhibits smooth multiplicative intensity inhomogeneity consistent with MRI B1-field non-uniformity. The phantom contains lateral ventricles.

Label semantics: 0=background, 1=CSF (including ventricles), 2=gray matter, 3=white matter.

Write `/app/pipeline.py` to produce conformant output in `/app/output/`.

**Output files:**
- `corrected.nii.gz` — corrected brain image (float32)
- `labels_corrected.nii.gz` — corrected label map (int16, values in {0,1,2,3})
- `bias_field.nii.gz` — estimated multiplicative bias field in output geometry (float32, strictly positive, spatially smooth)
- `metrics.json` — quality report

**Conformance requirements:**
- Canonical RAS+ orientation with strictly axis-aligned (diagonal) affine matrix
- Isotropic 2.0 mm voxel spacing
- Multiplicative intensity inhomogeneity estimated and divided out before any intensity normalization
- Brain-masked z-normalization: over voxels with label > 0, mean approximately 0 and standard deviation approximately 1
- After correction and normalization, within-tissue intensity standard deviation must be below 0.20 for white matter and below 0.25 for gray matter
- Fisher discriminant ratio between GM and WM — (mean(WM) - mean(GM))^2 / (var(WM) + var(GM)) — must exceed 6.0
- Volume cropped to brain bounding box with exactly 4 voxels of padding on each side
- All three output volumes must share identical shape and affine
- Voxel-to-world coordinate mapping must remain geometrically correct through all transforms

**metrics.json keys (computed on final output volume):**
- `shape`: [x, y, z] output dimensions
- `spacing`: [sx, sy, sz] voxel spacing in mm
- `orientation`: 3-letter NIfTI orientation code
- `wm_std`: white matter voxel intensity standard deviation
- `gm_std`: gray matter voxel intensity standard deviation
- `bias_field_range`: [min, max] of estimated bias field over brain mask
- `snr`: mean(WM) / std(background)
- `cnr`: |mean(GM) - mean(WM)| / sqrt(0.5 * (var(GM) + var(WM)))
- `brain_center_ras`: [R, A, S] world coordinates of brain mask centroid
- `fisher_gm_wm`: (mean(WM) - mean(GM))^2 / (var(WM) + var(GM))

`nibabel`, `numpy`, and `scipy` are available in the environment.