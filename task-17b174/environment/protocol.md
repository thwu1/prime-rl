# ActEV18_AD Evaluation Protocol Specification

## 1. Overview

The ActEV18_AD (Activity Detection) protocol evaluates temporal activity detection
systems by comparing system-generated detections against ground-truth reference
annotations across video files. The scorer computes detection performance metrics
at both per-activity and aggregate levels.

## 2. Input Formats

### 2.1 Reference Annotations (`reference.json`)

```json
{
  "activities": [
    {
      "activity": "<activity_name>",
      "activityID": <integer>,
      "localization": {
        "<filename>": {
          "<frame_number>": 0_or_1,
          ...
        }
      }
    },
    ...
  ]
}
```

### 2.2 System Output (`system_output.json`)

Same structure as reference, with an additional `presenceConf` field (float in
[0,1]) representing the system's confidence that the activity is present.

```json
{
  "filesProcessed": ["<filename>", ...],
  "activities": [
    {
      "activity": "<activity_name>",
      "activityID": <integer>,
      "presenceConf": <float>,
      "localization": { ... }
    },
    ...
  ]
}
```

### 2.3 Sparse Signal Localization

Localizations use a "sparse signal" encoding. Each localization maps filenames
to dictionaries of frame-number/value pairs. A value of `1` at frame `f` means
the signal turns ON at frame `f`; a value of `0` means it turns OFF. This
encodes half-open intervals `[start, end)`:

    {"100": 1, "200": 0}  =>  interval [100, 200)  =>  100 frames

Frame numbers are stored as string keys and must be parsed to integers. Entries
should be processed in ascending frame order.

### 2.4 File Index (`file_index.json`)

```json
{
  "<filename>": {
    "framerate": <float>,
    "selected": { "<frame>": 0_or_1, ... }
  }
}
```

The `selected` field uses the same sparse signal encoding to indicate which
portions of each file are included in evaluation. The total selected frame count
for a file is the sum of interval lengths from the `selected` signal.

### 2.5 Activity Index (`activity_index.json`)

```json
{
  "<activity_name>": {},
  ...
}
```

Lists all activities to be scored. Activities present in the index but absent
from the reference are skipped (no scoring if num_ref = 0).

### 2.6 Scoring Parameters (`scoring_parameters.json`)

```json
{
  "iou_threshold": <float>,
  "p_miss_at_rfa_targets": [<float>, ...],
  "naudc_at_rfa_targets": [<float>, ...],
  "nmide_collar_size": <int>,
  "nmide_cost_miss": <float>,
  "nmide_cost_fa": <float>
}
```

## 3. Scoring Pipeline

### 3.1 Total Duration

Compute the total evaluation duration in **minutes**:

    total_minutes = SUM over all files f:
        selected_frames(f) / framerate(f) / 60.0

where `selected_frames(f)` is the total frame count from the file's `selected`
sparse signal.

### 3.2 Per-Activity Scoring

For each activity listed in the activity index that has at least one reference
instance (num_ref > 0):

#### 3.2.1 Temporal IoU

For two sets of intervals A and B (within the same file):

    intersection = SUM of overlap between every pair (a, b) where a in A, b in B
                   overlap(a, b) = max(0, min(a_end, b_end) - max(a_start, b_start))

    area(X) = SUM of (end - start) for each interval in X

    union = area(A) + area(B) - intersection

    IoU = intersection / union    (0 if union = 0)

When a reference and system instance share multiple files, compute IoU per file
and take the maximum across files.

#### 3.2.2 Bipartite Alignment

Construct an IoU matrix of shape (num_ref, num_sys). Filter to valid pairs
where IoU is **strictly greater than** `iou_threshold`.

Build a cost matrix initialized to a large value (e.g., 1e6). For valid pairs,
set cost = -IoU (minimizing cost maximizes IoU).

Solve the optimal bipartite assignment to find the minimum-cost one-to-one
matching. Retain only assignments where the pair is
valid (IoU > threshold).

The result is a list of matched (ref_index, sys_index) pairs.

#### 3.2.3 DET Curve Construction

The Detection Error Tradeoff (DET) curve traces P_miss vs. Rate of False Alarms
(RFA) as the confidence threshold is swept.

Start with an implicit point (RFA=0, P_miss=1.0) representing the operating
point where no detections are accepted.

For each unique confidence score (in descending order), compute the operating
point at that threshold:

    active_sys = {j : sys_confs[j] >= threshold}
    CD = count of matched system instances in active_sys   (correct detections)
    MD = num_ref - CD                                      (missed detections)
    FA = count of active_sys instances NOT in matched_sys   (false alarms)
    P_miss = MD / num_ref
    RFA = FA / total_minutes

Append (RFA, P_miss) to the DET curve.

`matched_sys` is the set of system indices that appear in any alignment pair
(computed once from the alignment, not per-threshold).

#### 3.2.4 P_miss at RFA Operating Points

For each target RFA value `t`:

    P_miss@RFA_t = min { p_miss : (rfa, p_miss) in DET_curve AND rfa <= t }

If no DET curve points satisfy rfa <= t, default to 1.0.

#### 3.2.5 Normalized AUDC (nAUDC)

For each target RFA value `t`:

1. Filter DET points to those with rfa <= t.
2. Compute the area under the curve using **trapezoidal integration**:

       area = SUM over consecutive filtered points (x_k, y_k), (x_{k+1}, y_{k+1}):
              (x_{k+1} - x_k) * (y_k + y_{k+1}) / 2

3. Normalize: nAUDC = area / t

If t = 0, nAUDC = 0.

#### 3.2.6 N-MIDE (Normalized Minimum Instance-level Detection Error)

For each matched pair (ref_idx, sys_idx), compute the instance-level detection
error considering a **temporal collar**.

The collar parameter `c` (in frames) defines tolerance zones at the start and
end of each reference interval. Within these zones, temporal misalignment is
not penalized.

For each matched pair, find the shared file and process the intervals:

**Step 1: Construct collar-adjusted intervals**

For each reference interval `[rs, re)`:
- Core interval (for miss): `[rs + c, re - c)` (skip if `re - c <= rs + c`)
- Expanded interval (for FA): `[rs - c, re + c)`

**Step 2: Compute miss time**

    miss_time = area(core_intervals) - temporal_intersection(core_intervals, sys_intervals)

    miss_rate = miss_time / area(core_intervals)     (0 if area = 0)

**Step 3: Compute false alarm time**

    fa_time = area(sys_intervals) - temporal_intersection(sys_intervals, expanded_intervals)

    fa_rate = fa_time / (file_duration - area(expanded_intervals))

where `file_duration` is the total selected frame count for this file.
If the denominator is 0, fa_rate = 0.

**Step 4: Instance MIDE**

    MIDE_i = cost_miss * miss_rate + cost_fa * fa_rate

**Step 5: Aggregate**

    N-MIDE = mean(MIDE_i)  over all matched pairs

If there are no matched pairs, N-MIDE = 0.0.

**Note on collar = 0**: When the collar is 0, core intervals equal the original
reference intervals and expanded intervals also equal the originals, reducing
the formula to the standard (uncollared) N-MIDE.

### 3.3 Instance Counts

For each activity (at the lowest threshold, i.e., all detections active):

    num_correct = number of matched pairs
    num_missed = num_ref - num_correct
    num_false_alarm = num_sys - num_correct

### 3.4 Aggregation

Compute macro-average across all scored activities for each float-valued metric
(p_miss, nAUDC, n_mide). Integer counts (num_ref, num_sys, etc.) are NOT
aggregated.

## 4. Output Format

### 4.1 scores_by_activity.csv

Header row followed by one row per scored activity, sorted alphabetically by
activity name.

Columns in order:
```
activity, num_ref, num_sys, num_correct, num_missed, num_false_alarm,
p_miss_at_rfa_<t1>, p_miss_at_rfa_<t2>, ...,
naudc_at_rfa_<t1>, naudc_at_rfa_<t2>, ...,
n_mide
```

Where `<t1>, <t2>, ...` are the target values sorted in **ascending** order.

All float values formatted to exactly 5 decimal places. Integer values as plain
integers (no decimal point).

### 4.2 scores_aggregated.csv

Header row with columns `metric,value`. One row per aggregated metric, sorted
alphabetically by metric name. Values formatted to 5 decimal places.

## 5. Command-Line Interface

```
python3 scorer.py \
    --reference <path> \
    --system-output <path> \
    --activity-index <path> \
    --file-index <path> \
    --scoring-parameters <path> \
    --output-dir <path>
```

All arguments are required. The scorer creates the output directory if it does
not exist and writes `scores_by_activity.csv` and `scores_aggregated.csv`.
