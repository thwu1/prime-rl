A REST API server at `http://localhost:8080` serves six ARC-AGI tasks. Each task contains training input/output grid pairs (lists-of-lists of integers 0-9) and test inputs with withheld outputs.

Retrieve all tasks from the API, infer each transformation rule from its training examples, and submit correct test output grids back through the API's submit endpoint. Direct writes to `/app/outputs/` without going through the API are not tracked and will fail verification.

Populate the `solve_log` table in `/app/pipeline.db` (SQLite, pre-created) with a row per solved task. Schema: `task_id TEXT PK, input_rows INT, input_cols INT, output_rows INT, output_cols INT, num_colors INT, transformation_type TEXT`. `num_colors` is the count of distinct integer values in the output grid. `transformation_type` must be a non-empty descriptive label.

Generate a PNG visualization of each test output grid at `/app/visualizations/{task_id}_test_0.png` using ImageMagick. Each grid cell is a 20x20 pixel square. ARC color palette: 0=#000000 1=#0074D9 2=#FF4136 3=#2ECC40 4=#FFDC00 5=#AAAAAA 6=#F012BE 7=#FF851B 8=#7FDBFF 9=#870C25.

**API reference:**

| Method | Endpoint | Body / Response |
|--------|----------|-----------------|
| GET | `/api/tasks` | `{"tasks": [{"task_id", "num_train", "num_test"}, ...]}` |
| GET | `/api/tasks/{id}` | `{"task_id", "data": {"train": [...], "test": [...]}}` |
| POST | `/api/tasks/{id}/submit` | Body: `{"test_outputs": [grid, ...]}` -> `{"status": "accepted"}` |
| GET | `/api/submissions` | `{"submissions": [{"task_id", "submitted_at"}, ...]}` |