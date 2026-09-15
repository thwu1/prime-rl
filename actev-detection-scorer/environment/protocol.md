# Temporal Activity Detection Evaluation Protocol

## Data Schema

### Reference Database (SQLite)

- **videos** (`id INTEGER PRIMARY KEY`, `filename TEXT`, `num_frames INTEGER`)
- **activity_types** (`id INTEGER PRIMARY KEY`, `name TEXT`)
- **annotators** (`id INTEGER PRIMARY KEY`, `name TEXT`)
- **reference_annotations** (`id INTEGER PRIMARY KEY`, `activity_type_id INTEGER`, `video_id INTEGER`, `annotator_id INTEGER`, `start_frame INTEGER`, `end_frame INTEGER`)

Frame intervals are closed: both endpoints are included. Duration = `end_frame - start_frame + 1`.

### System Detections (JSONL)

Fields: `activity` (string), `video` (string), `start` (int), `end` (int), `score` (float).

### Configuration (TOML)

```toml
[evaluation]
alignment_mode = "iou" | "collar"
iou_threshold = <float>
collar_frames = <int>
pfa_max = <float>

[consensus]
enabled = <bool>
consensus_iou_threshold = <float>
include_singletons = <bool>

[decision_cost]
c_miss = <float>
c_fa = <float>
p_target = <float>

[data]
database = "<path>"
detections = "<path>"
```

## Temporal IoU

For two frame intervals [a, b] and [c, d] belonging to the same video:

- Intersection length: `max(0, min(b, d) - max(a, c) + 1)`
- Union length: `max(b, d) - min(a, c) + 1`
- `IoU = intersection / union` when intersection > 0, else 0

Cross-video IoU is always 0.

## Multi-Annotator Consensus

When consensus is enabled, reference annotations are consolidated into consensus references before evaluation proceeds.

For each (activity type, video) group, construct the optimal one-to-one assignment between annotations of each annotator pair that maximizes total temporal IoU. Pairs whose IoU ≥ `consensus_iou_threshold` yield consensus references whose temporal extent equals the intersection of the matched intervals (latest start, earliest end). All remaining annotations — unmatched, below threshold, or from single-annotator groups — are singletons, retained only when `include_singletons` is true.

## Detection–Reference Alignment

Per activity type, compute the minimum-cost one-to-one assignment between consensus references and system detections, subject to eligibility constraints.

**IoU mode:** a (reference, detection) pair is eligible iff they share a video and their temporal IoU ≥ `iou_threshold`. Cost = `1 − IoU`.

**Collar mode:** a pair is eligible iff they share a video and both `|det.start − ref.start| ≤ collar_frames` and `|det.end − ref.end| ≤ collar_frames`. Cost = `max(|start diff|, |end diff|) / collar_frames`.

Ineligible pairs are excluded. Assigned pairs are true positives (TP). Unassigned detections are false positives (FP). Unassigned references are false negatives (FN).

## DET Curve

Per activity, the Detection Error Tradeoff curve traces (Pfa, Pmiss) operating points as an implicit decision threshold sweeps detection confidences from +∞ to −∞. At tied confidence values, true positives are accepted before false positives.

Let T = sum of `num_frames` across all videos.

- `Pfa = (cumulative FP) / T`
- `Pmiss = 1 − (cumulative TP) / n_ref`

The curve originates at the reject-all point (0, 1). If the final operating point has Pfa < `pfa_max`, the curve extends horizontally to (pfa_max, final Pmiss).

Zero-detection activities: curve is [(0, 1), (pfa_max, 1)].

## Metrics

### Per-Activity

- **AUDC**: Trapezoidal area under the DET curve.
- **nAUDC**: `AUDC / pfa_max`. Equals 1.0 for zero-detection activities with references.
- **tw_Pmiss**: Duration-weighted miss probability — each reference's contribution to the miss rate is weighted by its frame duration (`end − start + 1`). The time-weighted DET curve substitutes tw_Pmiss for Pmiss at each operating point. **tw_AUDC** and **tw_nAUDC** are the trapezoidal area and its normalized form under this curve.
- **MinNDCF**: Minimum Normalized Detection Cost Function. Over all DET curve operating points including the reject-all point (Pmiss=1, Pfa=0):

  `DCF(τ) = C_miss · P_target · Pmiss(τ) + C_fa · (1 − P_target) · Pfa(τ)`

  `MinNDCF = min_τ DCF(τ) / min(C_miss · P_target, C_fa · (1 − P_target))`

  Zero-reference activities: MinNDCF = 0.

### Aggregate

- **mean_nAUDC**: Arithmetic mean of per-activity nAUDC.
- **weighted_mean_nAUDC**: Mean of per-activity nAUDC weighted by per-activity reference count.
- **mean_tw_nAUDC**: Arithmetic mean of per-activity tw_nAUDC.
- **mean_MinNDCF**: Arithmetic mean of per-activity MinNDCF.

## Output

All files in `--output-dir`. Float values to 6 decimal places.

### scores_by_activity.csv

Rows sorted alphabetically by activity name.

```
activity,nAUDC,AUDC,tw_nAUDC,tw_AUDC,MinNDCF,n_ref,n_sys
```

### scores_aggregated.csv

```
metric,value
mean_nAUDC,<float>
weighted_mean_nAUDC,<float>
mean_tw_nAUDC,<float>
mean_MinNDCF,<float>
```

### det_curves.json

```json
{
  "<activity>": {
    "points": [[pfa, pmiss], ...]
  }
}
```

Float values rounded to 6 decimal places.

## CLI

```
python3 /app/scorer.py --config <toml_path> --output-dir <output_dir>
```
