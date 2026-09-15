# 3D Object Detection Evaluation Protocol

## 1. Overview

This document specifies the evaluation protocol for 3D object detection in
autonomous driving scenarios. The evaluator computes per-category metrics for
detection predictions against ground truth annotations, producing a Composite
Detection Score (CDS) as the primary ranking metric.

## 2. Data Format

### 2.1 Detection Predictions

Stored as an Apache Feather file (`detections.feather`). Each row represents
one detection with these columns:

| Column       | Type   | Description                                     |
|--------------|--------|-------------------------------------------------|
| log_id       | string | Unique identifier for the driving log           |
| timestamp_ns | int64  | Timestamp in nanoseconds                        |
| category     | string | Object category label                           |
| tx, ty, tz   | float  | Center position in ego-vehicle frame (meters)   |
| length       | float  | Extent along object x-axis (meters)             |
| width        | float  | Extent along object y-axis (meters)             |
| height       | float  | Extent along object z-axis (meters)             |
| yaw          | float  | Heading angle in radians, range [-pi, pi]       |
| score        | float  | Detection confidence (higher = more confident)  |

### 2.2 Ground Truth Annotations

Stored as an Apache Feather file (`ground_truth.feather`). Same spatial columns
as detections, plus:

| Column           | Type  | Description                               |
|------------------|-------|-------------------------------------------|
| num_interior_pts | int64 | Number of LiDAR points inside the cuboid  |

## 3. Evaluation Pipeline

### 3.1 Range Filtering

Remove all detections and ground truth annotations whose center is beyond
`max_range_m` meters from the ego vehicle origin. The range is computed as
the **Euclidean (L2) norm** of the 3D center position vector:

```
range = sqrt(tx² + ty² + tz²)
```

Objects with `range >= max_range_m` are excluded. Note: this is the L2 norm,
**not** the L-infinity (Chebyshev) norm `max(|tx|, |ty|, |tz|)`.

### 3.2 Ground Truth Filtering

Remove ground truth annotations with `num_interior_pts == 0`, as these lack
sufficient LiDAR evidence for reliable annotation.

### 3.3 Detection Limiting

For each sweep (unique `(log_id, timestamp_ns)` pair) and each category,
retain only the top `max_detections_per_category` detections ranked by
confidence score in descending order.

### 3.4 Greedy Assignment

For each sweep and category, assign detections to ground truth annotations
using a greedy matching procedure:

1. **Sort detections in descending order by confidence score** (highest first).
2. Process each detection in this sorted order:
   - Compute 3D Euclidean center distance to every **unmatched** ground truth:
     ```
     d(dt, gt) = sqrt((dt.tx - gt.tx)² + (dt.ty - gt.ty)² + (dt.tz - gt.tz)²)
     ```
   - Find the closest unmatched ground truth within the distance threshold.
   - If a match is found: record the `(detection_index, gt_index)` pair and
     mark the ground truth as matched (unavailable for future assignments).
   - If no match: the detection is a false positive.

3. Return a mapping from detection indices to matched ground truth indices.

The procedure is performed **independently** at each of four affinity
thresholds: `{0.5, 1.0, 2.0, 4.0}` meters (configurable via `config.toml`).

**Critical detail:** Detections must be processed in **descending** score
order. Processing in ascending order would allow low-confidence detections
to claim ground truth objects before high-confidence ones, corrupting the
precision–recall curve.

If either the detection list or ground truth list is empty, return an empty
mapping.

### 3.5 Average Precision (AP)

After processing all sweeps for a given category at one affinity threshold:

1. Collect all detections across all sweeps and sort globally by score in
   descending order.

2. Compute cumulative true positives (`cum_tp`) and false positives (`cum_fp`)
   along the score-sorted list.

3. Compute precision and recall at each position:
   ```
   precision[i] = cum_tp[i] / (cum_tp[i] + cum_fp[i])
   recall[i]    = cum_tp[i] / total_num_gts
   ```

4. Apply **VOC-style precision interpolation** (monotonic envelope). Replace
   precision at each recall level with the maximum precision at any recall
   level greater than or equal to the current level:
   ```
   p_interp(r) = max_{r' >= r} p(r')
   ```
   Implementation: `precision = np.maximum.accumulate(precision[::-1])[::-1]`

   This ensures that precision is a non-increasing function of recall, which
   prevents artificial AP deflation from precision oscillations.

5. Sample precision at `num_recall_samples` (default 101) equally-spaced
   recall points in `[0, 1]` using `np.interp`. Precision is 0 for recall
   values beyond the maximum achieved recall (use `right=0`).

6. AP = arithmetic mean of the sampled precision values.

The final AP for the category is the arithmetic mean across all affinity
thresholds.

If there are no detections or no ground truth, AP = 0.

### 3.6 True Positive Error Metrics

TP errors are computed only for true positive matches at the
`tp_threshold_m` distance (default 2.0m). Each metric is averaged across
all TPs for the category.

#### 3.6.1 Average Translation Error (ATE)

```
ATE = mean( ||t_dt - t_gt||₂ )   for all TPs
```

where `t` is the 3D center position vector. Normalization upper bound:
`tp_norms.ATE` (default 2.0 meters).

#### 3.6.2 Average Scale Error (ASE)

```
ASE = mean( 1 - IoU_aligned )   for all TPs
```

where `IoU_aligned` is the axis-aligned dimension overlap:
```
IoU_aligned = prod_{i ∈ {l,w,h}} min(d_i^dt, d_i^gt) / max(d_i^dt, d_i^gt)
```

Normalization upper bound: `tp_norms.ASE` (default 1.0).

#### 3.6.3 Average Orientation Error (AOE)

```
AOE = mean( |wrap(yaw_dt - yaw_gt)| )   for all TPs
```

where `wrap(θ)` normalizes the angle difference to `[-π, π]`:
```
wrap(θ) = atan2(sin(θ), cos(θ))
```

This handles the circular nature of angles correctly. Without wrapping,
headings near +π and -π would produce an error of ~2π instead of the
correct small angular difference.

Normalization upper bound: `tp_norms.AOE` (default π radians).

#### 3.6.4 Default Values

If no true positives exist at the TP threshold for a category, use the
upper-bound error values from `tp_norms`:
- ATE = `tp_norms.ATE`
- ASE = `tp_norms.ASE`
- AOE = `tp_norms.AOE`

### 3.7 Composite Detection Score (CDS)

CDS combines detection performance (AP) with localization quality:

```
CDS = AP × mean(ATM, ASM, AOM)
```

where the True Positive Measures are the clamped complements of normalized
errors:
```
ATM = clamp(1 - ATE / tp_norms.ATE, 0, 1)
ASM = clamp(1 - ASE / tp_norms.ASE, 0, 1)
AOM = clamp(1 - AOE / tp_norms.AOE, 0, 1)
```

The normalization constants are loaded from the configuration at
`evaluation.tp_norms.{ATE, ASE, AOE}`.

**Important:** CDS uses the **arithmetic mean** of the three TP measures,
not their sum. This ensures CDS ∈ [0, 1].

### 3.8 Category Averaging

The `AVERAGE_METRICS` entry is the arithmetic mean of per-category metric
values for each of AP, ATE, ASE, AOE, and CDS.

## 4. Output Format

Results are written as JSON with one entry per category plus `AVERAGE_METRICS`:

```json
{
    "CATEGORY_NAME": {
        "AP": 0.xxxx,
        "ATE": 0.xxxx,
        "ASE": 0.xxxx,
        "AOE": 0.xxxx,
        "CDS": 0.xxxx
    },
    "AVERAGE_METRICS": { ... }
}
```

All values are rounded to `output.decimal_places` (default 4) decimal places.

## 5. Configuration

All evaluation parameters are defined in `/app/config/main.toml`. This is the
authoritative configuration source. The parameter values specified in the table
below are the canonical protocol defaults.

| Parameter                        | Default          | Description                    |
|----------------------------------|------------------|--------------------------------|
| evaluation.affinity_thresholds_m | [0.5,1.0,2.0,4.0]| Distance thresholds for AP    |
| evaluation.tp_threshold_m        | 2.0              | TP distance threshold          |
| evaluation.max_range_m           | 150.0            | Maximum evaluation range       |
| evaluation.max_detections_per_category | 100         | Max detections per sweep       |
| evaluation.num_recall_samples    | 101              | AP recall sampling points      |
| evaluation.tp_norms.ATE          | 2.0              | ATE normalization (meters)     |
| evaluation.tp_norms.ASE          | 1.0              | ASE normalization              |
| evaluation.tp_norms.AOE          | π                | AOE normalization (radians)    |
| output.decimal_places            | 4                | Output rounding precision      |
