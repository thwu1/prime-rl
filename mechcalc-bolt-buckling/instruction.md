`/app/mechcalc.py` is a mechanical engineering analysis calculator with multiple defects. It reads JSON from stdin containing `bolt`, `buckling`, and `vbelt` sections and writes analysis JSON to stdout, but produces incorrect numerical results across several subsystems. Engineering reference documentation is available in `/app/docs/` and a sample input in `/app/inputs/`.

Diagnose and correct all defects in `/app/mechcalc.py` so that it produces accurate results for all three analysis modules, including proper handling of multi-part clamped joints, all six column mounting configurations (A through F), all four profile types (rectangle, circle, tube, I-beam), and complete belt force analysis. Then create two additional pipeline components:

**`/app/report.jq`** — a jq program that receives `{"input": <original_json>, "output": <mechcalc_output>}` on stdin and produces:

```json
{
  "modules": [
    {"name": "bolt", "pass": bool, "governing_safety": float, "required_safety": float, "margin_pct": float},
    {"name": "buckling", ...},
    {"name": "vbelt", ...}
  ],
  "overall_pass": bool,
  "min_margin_pct": float
}
```

`margin_pct = (governing_safety / required_safety - 1) * 100`. Bolt governing safety is `output.bolt.safety_yield`; required is `input.bolt.safety_yield_desired`. Buckling governing safety is the zone-appropriate safety factor from the calculator output; required is `input.buckling.safety_desired`. Vbelt governing safety is `output.vbelt.wrap_angle_small_deg / 90`; required is `1.0`. `overall_pass` is true only when all modules pass. `min_margin_pct` is the minimum margin across all modules.

**`/app/analyze.sh`** — executable shell script supporting three subcommands:

- `run <file.json>` — executes the full pipeline (mechcalc + report.jq), stores results in SQLite at `/app/results.db`, and prints the report JSON to stdout. The `runs` table schema: `id INTEGER PRIMARY KEY AUTOINCREMENT, input_file TEXT, timestamp TEXT, report_json TEXT, overall_pass INTEGER`.
- `history` — outputs a JSON array of all stored runs ordered by id descending, each containing `id`, `input_file`, `timestamp`, and `overall_pass`.
- `compare <id1> <id2>` — outputs JSON with a `modules` array (each entry has `name` and `margin_delta` computed as run id2's margin minus run id1's margin) and an `overall_delta` field comparing `min_margin_pct` values.
