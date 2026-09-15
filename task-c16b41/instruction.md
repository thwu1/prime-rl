Your organization operates ERNIEKit (PaddlePaddle) distributed training infrastructure across GPU clusters. Training launches routinely fail due to misconfigured YAML files — broken parallelism settings, missing precision flags, incompatible parameter combinations — wasting GPU-hours and blocking model iterations.

Five broken training configs are at `/app/configs/broken_[1-5].yaml` (YAML headers indicate the intended model and GPU count). Two known-valid reference configs are at `/app/configs/reference_*.yaml`. The model architecture registry is at `/app/models.json`. A validation manifest listing each config entry is at `/app/manifest.yaml`. Documentation is in `/app/docs/`.

Deliver three tools conforming to the CLI interfaces and output contracts specified in `/app/docs/api_contract.md`:

1. **`/app/validator.py`** — Validates training configs against ERNIEKit's distributed training constraints and produces auto-fixed versions that pass all checks.
2. **`/app/planner.py`** — Computes per-GPU memory estimates and generates hardware-optimal parallelism configurations for specified model/hardware combinations.
3. **`/app/pipeline.sh`** — Batch-processes all manifest entries, persists structured validation results in a normalized SQLite database, and emits an aggregate JSON report.

Success criteria: every broken config is flagged with its exact set of violations, reference configs validate clean, auto-fixed configs pass validation, memory estimates match the documented model within 0.01 GB, planned configurations minimize the specified cost function for given hardware, and the pipeline database and aggregate report contain correct statistics.