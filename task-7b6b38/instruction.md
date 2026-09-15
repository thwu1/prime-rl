A 4-layer INT4 quantized neural network is stored at `/app/model/` using heterogeneous formats and containers. The binary format specification at `/app/format_spec.md` documents the file structures but intentionally leaves certain implementation details unspecified — you must resolve these empirically.

The model directory contains weight files, scale files, zero-point files, an SQLite database (`calibration.db`), and possibly other container formats. Not all data files are in the same format or stored in the same way. Some data may have been corrupted during export.

Diagnostic data is available at `/app/known_weights/reference_values.json` and 5 pre-computed input/output pairs are at `/app/reference/` (`input_0.npy` through `input_4.npy` with corresponding `output_*.npy`).

Create `/app/inference.py` that:
- Accepts three command-line arguments: `<model_dir> <input_npy_path> <output_npy_path>`
- Loads and processes all model data to produce correct float32 inference results
- Saves the output as a `.npy` file at the specified path

Your implementation must reproduce the reference outputs to within `atol=5e-4, rtol=1e-3`.

Available tools: `xxd`, `hexdump`, `objdump`, `readelf`, `objcopy`, `sqlite3`, `python3`.