# ISLES Evaluation Protocol

## Context

The ISLES challenge evaluates automatic ischemic stroke lesion segmentation in T1-weighted brain MRI acquired across 60+ clinical centers. Submissions are scored against expert-delineated ground truth masks using voxel-level overlap, volumetric, surface-distance, and instance-level panoptic metrics.

## Inputs

- Ground truth and prediction masks are NIfTI-1 files (`.nii.gz`) in native acquisition space.
- Files are paired by filename across the ground truth and prediction directories.
- Prediction files may contain continuous probability values in [0, 1]. Values strictly greater than 0.5 are lesion-positive; all others are background.

## Metrics

### Dice Similarity Coefficient (DSC)

Binary voxel overlap between ground truth and prediction.

### Absolute Volume Difference (AVD)

Absolute difference in total lesion volume, in milliliters. Volume computation must faithfully reflect the full voxel-to-world spatial geometry — including any anisotropy, rotation, and shear encoded in the image header.

### Average Symmetric Surface Distance (ASSD)

Mean of the directed surface distances from ground truth to prediction and from prediction to ground truth, in physical millimeters. Surface voxels are the face-connected boundary voxels of each binary mask. Distances are Euclidean in the physical coordinate system defined by the NIfTI affine transformation.

### 95th Percentile Hausdorff Distance (HD95)

The 95th percentile of the pooled directed surface distances (ground truth to prediction and prediction to ground truth), in physical millimeters.

### Lesion-wise F1 Score

Instance-level detection metric. Individual lesion instances are maximal face-connected components in 3D. Ground truth and prediction instances are matched one-to-one using greedy assignment: candidate pairs are ranked by decreasing pairwise IoU and assigned in order, each instance participating in at most one match. A minimum IoU of 0.2 is required.

- TP = matched pairs
- FP = unmatched prediction instances
- FN = unmatched ground truth instances

### Panoptic Quality (PQ)

PQ = SQ × RQ, where RQ equals the lesion-wise F1, and SQ quantifies the voxel-level overlap quality of matched instance pairs.

### Instance Count Difference (ICD)

Absolute difference in the number of connected components between prediction and ground truth, independent of instance matching.

## Edge-Case Conventions

| Condition | DSC | AVD | ASSD | HD95 | F1 | PQ | ICD |
|---|---|---|---|---|---|---|---|
| Both masks empty | 1.0 | 0.0 | 0.0 | 0.0 | 1.0 | 1.0 | 0 |
| Exactly one mask empty | 0.0 | volume of non-empty mask | −1.0 | −1.0 | 0.0 | 0.0 | instance count of non-empty mask |
| Both non-empty, no instance matches | voxel-level value | voxel-level value | computed value | computed value | 0.0 | 0.0 | count difference |

## CLI Interface

```
python3 /app/evaluate.py --gt <gt_dir> --pred <pred_dir> --output <output.json>
```

## Output Schema

```json
{
  "per_case": {
    "<case_name>": {
      "dice": <float>,
      "avd_ml": <float>,
      "assd_mm": <float>,
      "hd95_mm": <float>,
      "lesion_f1": <float>,
      "panoptic_quality": <float>,
      "instance_count_diff": <int>,
      "num_gt_instances": <int>,
      "num_pred_instances": <int>
    }
  },
  "aggregate": {
    "mean_dice": <float>,
    "mean_avd_ml": <float>,
    "mean_assd_mm": <float>,
    "mean_hd95_mm": <float>,
    "mean_lesion_f1": <float>,
    "mean_panoptic_quality": <float>,
    "mean_instance_count_diff": <float>
  }
}
```

- `<case_name>` is the filename without the `.nii.gz` (or `.nii`) extension.
- Aggregate values are arithmetic means across all cases, except that cases where surface distance metrics are −1.0 are excluded from `mean_assd_mm` and `mean_hd95_mm`.
