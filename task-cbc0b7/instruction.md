Two ESP32 LED controller firmware implementations are provided in `/app/c_src/` (C/ESP-IDF/FreeRTOS) and `/app/rust_src/` (Rust/no_std/embassy). Both process JSON commands to drive LED patterns (blink, wave, off) with HSV color control and brightness modulation, but they are not behaviorally identical.

Identify all behavioral divergences between the two implementations and produce the following outputs in `/app/`:

**`/app/c_harness.c`** and **`/app/c_harness`** — C source and compiled binary. The binary must print a single JSON object to stdout containing:
- `"wave_table"`: the C firmware's brightness lookup table values
- `"wave_table_length"`: integer length of the table
- `"hsv_tests"`: array of objects with keys `h`, `s`, `v`, `r`, `g`, `b` showing C HSV-to-RGB results for at least these inputs: (0,1,1), (120,1,1), (240,1,1), (0,0,1), (0,0,0), (0,0.5,1), (-60,1,1), (720,1,1)

**`/app/c_pipeline.py`** and **`/app/rust_pipeline.py`** — Python modules each exposing:
- `process_hsv(h: float, s: float, v: float) -> tuple[int, int, int]` — HSV to RGB matching the respective firmware's behavior across the complete input domain (standard hue, negative hue, hue >360, zero saturation, zero value)
- `generate_wave_table() -> list[int]` — Brightness table matching the respective firmware
- `compute_pattern_timing(period_ms: int, duty_cycle_pct: int, pattern: str) -> dict` — For `"blink"`: `on_ms`, `off_ms`, `total_cycle_ms`. For `"wave"`: `tick_ms`, `table_entries`, `wave_phase_ms`, `gap_ms`, `total_cycle_ms`. For `"off"`: `{"total_cycle_ms": 0}`

The C harness output and `c_pipeline` must produce consistent results.

**`/app/analyzer.py`** — Generates `/app/divergence_report.json`.

**`/app/divergence_report.json`** — `{"divergences": [...]}` where each entry contains: `id` (string), `category` (one of: `color_conversion`, `wave_table`, `pattern_timing`, `input_validation`, `bug`), `severity` (`critical`/`high`/`medium`/`low`), `description` (string), `c_behavior` (string), `rust_behavior` (string), `test_input` (object). Must contain at least 5 divergences spanning at least 3 categories, including identification of an array bounds bug in one implementation.