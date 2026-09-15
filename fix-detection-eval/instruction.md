Implement `/app/evaluate.py` — a complete evaluation pipeline conforming to the Argoverse 2 Scene Flow benchmark protocol.

## Data

- **Annotations**: `/app/data/annotations/<scene_id>.npz` — arrays `flow` (N×3 float64), `is_dynamic` (N bool), `category_indices` (N uint8), `is_close` (N bool), `is_valid` (N bool).
- **Predictions**: `/app/data/predictions/<scene_id>.feather` — columns `flow_tx_m`, `flow_ty_m`, `flow_tz_m` (float16) and `is_dynamic` (bool). Row count matches the corresponding annotation.
- **Configuration**: `/app/config.json` — thresholds, category mappings, time delta, and I/O paths.

Scenes are matched by `<scene_id>` between annotation and prediction directories. Only valid points participate in evaluation. Predictions stored as float16 must be upcast to float64 before computation.

## Requirements

Compute the standard av2 scene flow metrics — EPE, dual-threshold accuracy (strict and relax), and 4D space-time angle error — plus binary dynamic segmentation IoU. Metrics are broken down by Class (Foreground/Background) × Motion (Dynamic/Static) × Distance (Close/Far) subsets. The protocol's conventionally excluded class-motion combination must be omitted. Produce both per-distance and distance-aggregated results using count-weighted cross-scene averaging. The composite `EPE_3Way` is the mean of three specific distance-aggregated EPE values. `Dynamic_IoU` uses globally-accumulated segmentation counts across all scenes. Use epsilon-guarded division where appropriate.

## Output

Write `/app/results.json`:

```json
{
  "metrics": {
    "MetricName/Class/Motion/Distance": ...,
    "MetricName/Class/Motion": ...
  },
  "EPE_3Way": ...,
  "Dynamic_IoU": ...
}
```

All numeric values rounded to 6 decimal places.