# 3D Object Detection Evaluation: Composite Detection Score (CDS)

## Overview

Evaluate 3D object detection predictions against ground truth annotations using the
Composite Detection Score (CDS) framework. CDS combines Average Precision (AP) with
true positive error metrics (ATE, ASE, AOE) into a single ranking metric.

## Input Data

**Dataset**: `/app/data/dataset.json`

```json
{
  "sweeps": [
    {
      "log_id": "log_000",
      "timestamp_ns": 1000000000,
      "ground_truth": [ { "category": "...", "tx_m": ..., ... } ],
      "detections": [ { "category": "...", "tx_m": ..., "score": ..., ... } ]
    }
  ],
  "categories": ["REGULAR_VEHICLE", "PEDESTRIAN", "CYCLIST", "LARGE_VEHICLE", "BOLLARD"],
  "config": {
    "affinity_thresholds_m": [0.5, 1.0, 2.0, 4.0],
    "tp_threshold_m": 2.0,
    "max_range_m": 150.0,
    "max_num_dts_per_category": 100,
    "num_recall_samples": 101
  }
}
```

Each object has:
- **Position**: `tx_m, ty_m, tz_m` — 3D center in ego-vehicle frame (meters)
- **Dimensions**: `length_m, width_m, height_m` — bounding box extents (meters)
- **Orientation**: `qw, qx, qy, qz` — unit quaternion (scalar-first convention)
- **GT only**: `num_interior_pts` — number of LiDAR points inside the cuboid
- **Detection only**: `score` — confidence score

## Evaluation Pipeline

### Step 1: Filtering (per sweep, per category)

For each (sweep, category) group:

1. **GT range filter**: Remove GT where `sqrt(tx² + ty² + tz²) >= max_range_m`
2. **GT interior filter**: Remove GT where `num_interior_pts == 0`
3. **Detection range filter**: Remove detections where `sqrt(tx² + ty² + tz²) >= max_range_m`
4. **Detection sort**: Sort remaining detections by `score` in **descending** order
5. **Detection cap**: Keep at most `max_num_dts_per_category` (100) detections

### Step 2: Assignment (per sweep, per category)

Given `N` filtered/sorted detections and `M` filtered ground truth objects:

1. Compute the **affinity matrix** `A` of shape `(N, M)`:
   ```
   A[i, j] = -||center_det_i - center_gt_j||₂
   ```
   where centers are 3D positions `(tx_m, ty_m, tz_m)`.

2. For each detection `i`, find its closest GT:
   ```
   closest_gt[i] = argmax_j(A[i, j])
   ```

3. **Resolve duplicates**: When multiple detections claim the same GT, only the
   first one (highest score, since detections are sorted descending) keeps the
   assignment. Use `numpy.unique(closest_gt, return_index=True)` to find the
   unique GT indices and the index of the first detection assigned to each.

4. For each assigned detection-GT pair `(det_k, gt_m)`:
   - For each threshold `d` in `affinity_thresholds_m`: it is a **true positive**
     if `A[det_k, gt_m] > -d` (equivalently, `distance < d`).
   - At the **TP threshold** (`tp_threshold_m = 2.0`, selected as
     `thresholds[len(thresholds) // 2]`), compute the TP error metrics.

5. Unassigned detections and assigned detections beyond the threshold are
   **false positives** at that threshold.

### Step 3: Average Precision (per category)

For each category, **aggregate all detections across all sweeps** and sort them
globally by `score` descending. For each distance threshold `d`:

1. Build the TP/FP sequence using the assignments from Step 2.
2. Compute cumulative counts:
   ```
   cum_tp[k] = sum(tp[0..k])
   cum_fp[k] = sum(fp[0..k])
   ```
3. Compute precision and recall:
   ```
   precision[k] = cum_tp[k] / (cum_tp[k] + cum_fp[k] + ε)    where ε = 1e-6
   recall[k] = cum_tp[k] / num_gts_total
   ```
   where `num_gts_total` is the total number of valid GTs for this category across all sweeps.

4. **VOC-style precision interpolation** (envelope from right):
   ```
   precision_interp = numpy.maximum.accumulate(precision[::-1])[::-1]
   ```

5. Sample at `num_recall_samples` (101) evenly spaced recall points:
   ```
   recall_points = numpy.linspace(0, 1, 101, endpoint=True)
   precision_sampled = numpy.interp(recall_points, recall, precision_interp, right=0)
   ```

6. `AP_d = mean(precision_sampled)`

Per-category mean AP:
```
mAP_category = mean(AP_d  for d in affinity_thresholds_m)
```

### Step 4: True Positive Error Metrics (per category)

Computed over all TPs at the TP threshold (2.0m) across all sweeps for the category:

#### Average Translation Error (ATE)
```
ATE = mean(||det_center - gt_center||₂)  over all TPs
```
Default (no TPs): `ATE = tp_threshold_m = 2.0`

#### Average Scale Error (ASE)
```
ASE = mean(1 - IoU_3d_axis_aligned(det_dims, gt_dims))  over all TPs
```

**Axis-aligned 3D IoU** between boxes with dimensions `(l₁,w₁,h₁)` and `(l₂,w₂,h₂)`:
```
intersection = min(l₁,l₂) × min(w₁,w₂) × min(h₁,h₂)
union = l₁×w₁×h₁ + l₂×w₂×h₂ - intersection
IoU = intersection / union
```
Default (no TPs): `ASE = 1.0`

#### Average Orientation Error (AOE)

Extract yaw from quaternion:
```
yaw = atan2(2·(qw·qz + qx·qy),  1 - 2·(qy² + qz²))
```

Compute wrapped angular difference:
```
diff = yaw_det - yaw_gt
wrapped = ((diff + π) mod 2π) - π
AOE = mean(|wrapped|)  over all TPs
```
Default (no TPs): `AOE = π`

### Step 5: Composite Detection Score (per category)

```
CDS_category = mAP_category × mean(1 - ATE/2.0,  1 - ASE/1.0,  1 - AOE/π)
```

When defaults are used (no TPs), all TP scores are 0, so `CDS = 0`.

### Step 6: Overall Metrics

Simple average across all categories:
```
mAP = mean(mAP_category  for each category)
mATE = mean(ATE_category  for each category)
mASE = mean(ASE_category  for each category)
mAOE = mean(AOE_category  for each category)
CDS = mean(CDS_category  for each category)
```

## Output Format

Write to `/app/results.json`:
```json
{
  "per_category": {
    "REGULAR_VEHICLE": {"AP": 0.1234, "ATE": 0.5678, "ASE": 0.1234, "AOE": 0.2345, "CDS": 0.0567},
    "PEDESTRIAN": { ... },
    ...
  },
  "mean": {"AP": 0.1234, "ATE": 0.5678, "ASE": 0.1234, "AOE": 0.2345, "CDS": 0.0567}
}
```

All values must be rounded to **4 decimal places**.
