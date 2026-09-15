A GPU persistent matmul performance prediction system at `/app/` models kernel scheduling and throughput estimation for NVIDIA A100 hardware. The system is split across Python modules in `/app/modules/`:

- `tile_scheduler.py` — grouped tile ordering for L2 cache reuse
- `resource_model.py` — shared memory calculation and SM occupancy limits
- `roofline.py` — roofline performance estimation with wave quantization
- `analyzer.py` — workload analysis orchestration
- `data_loader.py` — SQLite database interface

Running `python3 /app/predict.py` generates `/app/results.json`. The current modules contain multiple interacting bugs that produce incorrect predictions. A correct reference output is at `/app/expected_output.json`.

All hardware specs, kernel tuning configurations, and workload dimensions live in the SQLite database at `/app/profiling.db`. The schema is not documented — explore it with `sqlite3` to understand the available tables and data.

The modules contain minimal documentation. Derive the correct algorithms from code structure, variable semantics, and GPU architecture principles. Diagnose and fix all bugs across the modules until the generated output matches the expected reference.