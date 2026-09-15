The environment at `/app/` contains a multi-stage object detection evaluation pipeline for pediatric wrist fracture annotations. Annotations are stored in a SQLite database at `/app/data/annotations.db` (created by running `/app/data/generate_dataset.py`). The pipeline is orchestrated by `/app/Makefile` with the entry point `make -C /app evaluate`.

Pipeline stages:

- **Extraction** (`/app/pipeline/extract.py`): queries the SQLite database and writes YOLO-format ground-truth files, prediction files, and an image-dimensions manifest to `/app/data/`
- **Evaluation**: computes COCO-compatible bounding-box detection metrics from the extracted files

The existing pipeline components contain bugs distributed across the Makefile, the SQL-based extraction script, and the metric computation code. Developer notes at `/app/pipeline/notes.txt` document the pipeline but contain inaccuracies. A broken reference evaluator exists at `/app/pipeline/evaluator.py`.

Fix the pipeline so that `make -C /app evaluate` produces a correct `/app/results.json`. The evaluator (invoked as `/app/evaluate.py` by the Makefile) must not import or depend on `pycocotools`.

**Output schema** (`/app/results.json`):

```json
{
  "mAP": {"0.5": float, "0.75": float, "0.5:0.95": float},
  "per_class": {
    "<class_name>": {
      "ap_0.5": float, "ap_0.75": float, "ap_0.5:0.95": float,
      "n_gt": int, "n_det": int,
      "optimal_f1": {"threshold": float, "f1": float, "precision": float, "recall": float}
    }
  },
  "per_size": {
    "small": {"ap_0.5:0.95": float, "n_gt": int},
    "medium": {"ap_0.5:0.95": float, "n_gt": int},
    "large": {"ap_0.5:0.95": float, "n_gt": int}
  }
}
```

**Success criteria:**

- `make -C /app evaluate` completes successfully end-to-end
- All `mAP` values match `pycocotools` reference within +/-0.02; per-class AP within +/-0.03; per-size AP within +/-0.05
- Classes with zero ground-truth: AP = 0, excluded from mAP averaging
- Per-size metrics use COCO-standard pixel-area categorization
- `optimal_f1`: per-class confidence threshold maximizing F1 at IoU 0.5
- All ground-truth annotations in the database must appear in the evaluation, including rows with optional metadata columns
- Extraction must produce files for every image in the database
- The evaluator must not reference `pycocotools`
