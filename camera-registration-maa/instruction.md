A set of 3D reconstructions produced by different camera pose estimation methods across multiple scenes is stored at `/app/data/`. Evaluation metadata is in a SQLite database at `/app/data/metadata.db`:

- Table `reconstructions` (columns: `id`, `method_name`, `scene_name`, `model_dir`, `is_ground_truth`): indexes all ground-truth and predicted reconstructions. The `model_dir` value is relative to `/app/data/`.
- Table `eval_config` (columns: `key`, `value`): key `"thresholds"` stores a JSON-encoded array of distance thresholds for evaluation.

Each reconstruction's `model_dir` directory contains camera poses in COLMAP sparse model text format (`images.txt` and `cameras.txt`).

For each non-ground-truth method and each distance threshold, compute the maximum fraction of cameras that can be simultaneously registered — i.e., whose world-space positions are brought within the threshold distance of their ground-truth counterparts by some similarity transform (uniform scale, rotation, translation) applied to the predicted camera positions. Average this fraction across all scenes to get accuracy at that threshold. The **mAA** (mean Average Accuracy) is the normalized area under the accuracy-vs-threshold curve (trapezoidal integration divided by the threshold range).

Write `/app/results.json`:

```json
{
  "thresholds": [0.01, 0.02, ...],
  "methods": {
    "<method_name>": {
      "mAA": <float>,
      "accuracies": {"0.01": <float>, "0.02": <float>, ...}
    }
  },
  "ranking": ["<best_method>", ..., "<worst_method>"]
}
```

Each accuracy value is keyed by its threshold as a string. The `ranking` list orders methods from highest to lowest mAA.