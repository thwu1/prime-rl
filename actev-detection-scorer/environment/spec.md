# Temporal Activity Detection Evaluation Protocol

## 1. Input Formats

### file_index.json
Lists video files with their frame counts.
```json
{
  "files": [
    {"name": "<filename>", "num_frames": <int>}
  ]
}
```

### activity_index.json
Lists activity types to be evaluated.
```json
{
  "activities": ["<activity_name>", ...]
}
```

### reference.json
Ground-truth activity annotations with inclusive frame ranges.
```json
{
  "activities": [
    {"activity": "<name>", "file": "<filename>", "start_frame": <int>, "end_frame": <int>}
  ]
}
```

### system_output.json
System detection predictions with confidence scores.
```json
{
  "activities": [
    {"activity": "<name>", "file": "<filename>", "start_frame": <int>, "end_frame": <int>, "confidence": <float>}
  ]
}
```

## 2. Scoring Procedure

Scoring is performed independently for each activity type listed in the activity index.

### 2.1 Temporal Intersection over Union (IoU)

For each pair of reference instance `r` and system detection `s` that belong to the **same video file**, compute temporal IoU:

- Frame ranges are **inclusive**: both `start_frame` and `end_frame` are included in the interval.
- `intersection_frames = max(0, min(r.end_frame, s.end_frame) - max(r.start_frame, s.start_frame) + 1)`
- `union_frames = max(r.end_frame, s.end_frame) - min(r.start_frame, s.start_frame) + 1`
- `IoU = intersection_frames / union_frames` if `intersection_frames > 0`, else `0.0`

Pairs in different video files always have IoU = 0.

### 2.2 Optimal Alignment

Construct a cost matrix `C[i][j]` for `n_ref` references x `n_sys` system detections:
- If `IoU(ref_i, sys_j) >= iou_threshold`: `C[i][j] = 1.0 - IoU(ref_i, sys_j)`
- Otherwise: `C[i][j] = 10^9` (representing infinity)

Apply the **Hungarian algorithm** (minimum-cost bipartite matching) to find the optimal assignment minimizing total cost. Use `scipy.optimize.linear_sum_assignment`.

A matched pair is **valid** only if `C[i][j] < 10^9`. Valid matches are true positives (TP). Unmatched system detections are false positives (FP). Unmatched references are false negatives (FN).

### 2.3 DET Curve Construction

Sort system detections for this activity by **descending confidence score**. When confidence scores tie, process matched detections before unmatched ones.

Build the DET curve as an ordered list of `(Pfa, Pmiss)` points:

1. Start with anchor point: `(0.0, 1.0)`
2. Maintain cumulative counters: `TP = 0`, `FP = 0`
3. For each detection in sorted order:
   - If it has a valid match: `TP += 1`
   - Otherwise: `FP += 1`
   - Compute `Pmiss = 1.0 - TP / n_ref` (if `n_ref > 0`)
   - Compute `Pfa = FP / T` where `T = sum of num_frames for all files in file_index`
   - Append `(Pfa, Pmiss)` to curve
4. **Extension**: append `(pfa_max, Pmiss_final)` where `pfa_max` is the `--pfa-max` CLI parameter (default 0.2) and `Pmiss_final` is the Pmiss of the last operating point. Only extend if the last Pfa < pfa_max.

**Edge case**: if `n_sys == 0`, the DET curve is `[(0.0, 1.0), (pfa_max, 1.0)]`.

### 2.4 Time-Weighted DET Curve

Construct a second DET curve using time-weighted miss probability:

- Each reference instance `r` has weight `w_r = r.end_frame - r.start_frame + 1` (its duration in frames).
- Total reference weight `W = sum of w_r for all references of this activity`.
- Maintain a cumulative matched weight `MW = 0`.
- For each detection in the same sorted order as section 2.3:
  - If matched to reference `r_i`: `MW += w_{r_i}`
  - `tw_Pmiss = 1.0 - MW / W` (if `W > 0`)
  - `Pfa` is computed identically to section 2.3
- The time-weighted DET curve follows the same anchor `(0.0, 1.0)` and extension rules as section 2.3.

**Edge case**: if `n_sys == 0`, both standard and time-weighted nAUDC are `1.0`.

### 2.5 Metrics

**AUDC** (Area Under DET Curve): Trapezoidal numerical integration over the DET curve points sorted by increasing Pfa:

```
AUDC = sum over consecutive pairs: (pfa_{i+1} - pfa_i) * (pmiss_i + pmiss_{i+1}) / 2
```

**nAUDC** (Normalized AUDC):
```
nAUDC = AUDC / pfa_max
```

If `n_sys == 0`: `nAUDC = 1.0` (all references missed).

Compute both standard AUDC/nAUDC (from section 2.3 curve) and time-weighted tw_AUDC/tw_nAUDC (from section 2.4 curve).

### 2.6 Aggregation

Compute the following aggregate metrics across all activities in the activity index:

- `mean_nAUDC`: arithmetic mean of per-activity nAUDC values
- `weighted_mean_nAUDC`: weighted mean of per-activity nAUDC, weighted by `n_ref` per activity (i.e., `sum(nAUDC_i * n_ref_i) / sum(n_ref_i)`)
- `mean_tw_nAUDC`: arithmetic mean of per-activity tw_nAUDC values

## 3. Output Formats

### scores_by_activity.csv
CSV with header row. Data rows sorted alphabetically by activity name. Float values formatted to 6 decimal places.
```
activity,nAUDC,AUDC,tw_nAUDC,tw_AUDC,n_ref,n_sys
```

### scores_aggregated.csv
CSV with header row. Float values formatted to 6 decimal places.
```
metric,value
mean_nAUDC,<float>
weighted_mean_nAUDC,<float>
mean_tw_nAUDC,<float>
```

### det_curves.json
JSON object mapping activity names to standard DET curve data:
```json
{
  "<activity>": {
    "points": [[pfa, pmiss], ...]
  }
}
```
Float values rounded to 6 decimal places.

## 4. CLI Interface

```
python3 /app/scorer.py \
  --reference <path> \
  --system-output <path> \
  --activity-index <path> \
  --file-index <path> \
  --iou-threshold <float, default 0.2> \
  --pfa-max <float, default 0.2> \
  --output-dir <path>
```
