A 3D medical image registration pipeline at `/app/` produces incorrect results across multiple failure modes. The system has several interacting components:

- `/app/transforms.py` — spatial transform library with defective implementations and unimplemented functions
- `/app/configs/pipeline.json` — pipeline step definitions with structural issues
- `/app/configs/settings.json` — pipeline parameters
- `/app/metadata.db` — SQLite database containing transform ordering constraints (`transform_constraints`), expected numerical results (`expected_results`), and ground truth registration parameters (`reference_data`)
- `/app/pipeline.py` — diagnostic runner that exercises the pipeline
- `/app/data/` — synthetic 3D volume and landmark data (`.npy` files)

The metadata database is the authoritative reference for correct behavior — it contains the expected intermediate outputs, the required step ordering constraints, and the ground truth registration parameters that the transform implementations should reproduce. The environment includes `sqlite3` and `jq`.

Fix all defects in `/app/transforms.py`. Implement `register_landmarks` (rigid-body point-set registration yielding a proper rotation with det(R)=+1) and `evaluate_alignment` (supporting `ncc` and `mse` metrics by resampling into the reference coordinate frame).

Fix `/app/configs/pipeline.json` so that step ordering satisfies all constraints stored in the database and the resample step references the correct spacing key from `settings.json`.

Create `/app/validate_pipeline.py` — a script that takes a pipeline JSON file path as its first argument, validates step ordering against all constraints in `/app/metadata.db`, prints `VALID` and exits 0 if compliant, or prints `INVALID: <reason>` for each violation and exits non-zero.