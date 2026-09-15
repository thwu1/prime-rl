The evaluation framework at `/app/` scores predictions for a retinal imaging challenge across three sub-tasks (pixel-level lesion segmentation, disease severity grading, anatomical landmark localization). A Make-based pipeline orchestrates data generation, evaluation, and result aggregation via `jq`. The framework has bugs in its scoring logic, an unimplemented data generator, and a broken Makefile pipeline.

**Goal:** `make -C /app all` must produce a valid report at `/app/output/report.json`, and `/app/bin/idrid-check` must exit 0.

**What exists in `/app/`:**
- `src/evaluate.py` — evaluator CLI (has bugs)
- `src/generate_synthetic.py` — synthetic data generator (not implemented)
- `Makefile` — pipeline orchestration via Make and jq (has bugs)
- `config/eval_spec.yaml` — data format specification and scoring rules
- `reference/cases.json` — reference cases with expected scores
- `bin/idrid-check` — validation harness (do not modify)

**Evaluator CLI:**
```
python3 /app/src/evaluate.py --task <TASK> --predictions <PATH> --ground-truth <PATH> --output-json <PATH>
```
`--task`: `lesion_segmentation`, `disease_grading`, or `localization`

**Generator CLI:**
```
python3 /app/src/generate_synthetic.py --task <TASK> --num-images <N> --output-dir <DIR> --seed <INT> --noise-level <FLOAT>
```
Must produce deterministic paired ground-truth and prediction data. With `--noise-level 0.0`, predictions must exactly match ground truth. For segmentation, generated masks must contain non-rectangular multi-region structures.

**Pipeline:** `make all` must chain: generate → evaluate → report. The `report` target uses `jq` to merge per-task JSON results into `/app/output/report.json` conforming to:
```json
{"segmentation": {...}, "grading": {...}, "localization": {...}, "pipeline_version": "1.0"}
```

**Constraints:**
- Do not modify files under `/app/bin/` or `/app/reference/`
- Output format specifications and edge-case behavior are defined in `/app/config/eval_spec.yaml`
- Fixed evaluator, completed generator, and fixed Makefile must remain at their current paths
