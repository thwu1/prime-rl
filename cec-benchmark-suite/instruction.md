The benchmark evaluator at `/app/benchmark.py` is intended to evaluate 12 shifted-and-rotated numerical optimization functions (F1–F12) and three constraint violation functions, writing results to `/app/results.json`. Currently it crashes or produces incorrect output for multiple functions.

The system has three layers: Python code (`/app/benchmark.py`), binary parameter data (`/app/data/*.npy`), and an SQLite specification/parameter database (`/app/benchmark.db`). Defects span multiple layers; no single source of information should be assumed error-free.

Fix all issues so that `python3 /app/benchmark.py` runs without error and writes a fully correct `/app/results.json`. Architecture and schema documentation is at `/app/README.md`.