Implement four tools under `/app/` that together form a catastrophe reinsurance loss calculation system.

**`/app/fmcalc.py`** — Financial module calculation engine.

```
python3 /app/fmcalc.py -p <dir> [-a 0|1] [-n] [--binary] < input > output
```

Reads loss records from stdin and a financial programme structure from four CSV files in `<dir>` (`fm_programme.csv`, `fm_profile.csv`, `fm_policytc.csv`, `fm_xref.csv`). All supported calculation rules and file schemas are documented in `/app/calcrules.md`. Writes insured-loss records to stdout.

Flags:
- `-a 0` (default): aggregate-level output. `-a 1`: back-allocate results to input items.
- `-n`: output net retained loss instead of gross insured loss.
- `--binary`: use binary stream format for both stdin and stdout.

CSV input columns: `event_id,item_id,sidx,loss` (also accepts `output_id` as the item column for pipeline chaining). CSV output columns: `event_id,output_id,sidx,loss`, ordered by `(event_id, output_id, sidx)`. Tolerance: 0.01 absolute.

**`/app/fmtobin.py`** — CSV loss stream to binary converter. Must accept both `item_id` and `output_id` column names.
```
python3 /app/fmtobin.py < losses.csv > losses.bin
```

**`/app/fmtocsv.py`** — Binary loss stream to CSV converter, emitting `output_id` column.
```
python3 /app/fmtocsv.py < losses.bin > losses.csv
```

**Binary format** (little-endian): `int32` stream_type=1 header; per-item block: `int32` event_id, `int32` item_id/output_id, then sample records each as `int32` sidx + `float64` loss, terminated by `int32` sidx=0.

**`/app/run_pipeline.sh`** — Reinsurance pipeline orchestrator.
```
bash /app/run_pipeline.sh <gul_csv> <direct_dir> <ri_dir> <output_db>
```

Processes ground-up losses from `<gul_csv>` through a direct insurance stage (using `<direct_dir>`) and a reinsurance stage (using `<ri_dir>`), producing a SQLite database at `<output_db>` with tables:
- `gross_loss(event_id INTEGER, output_id INTEGER, sidx INTEGER, loss REAL)` — direct stage output.
- `net_loss(event_id INTEGER, output_id INTEGER, sidx INTEGER, loss REAL)` — retained after reinsurance.
- `summary(event_id INTEGER, gross_total REAL, net_total REAL, ceded_total REAL)` — per-event totals; `ceded_total = gross_total - net_total`.

Must clean up all temporary resources on exit; exit 0 on success.

**Equivalence requirements:**
- `fmtobin | fmtocsv` round-trip preserves values within 0.01.
- `fmtobin | fmcalc --binary | fmtocsv` produces results identical to CSV-mode `fmcalc`.
- Output of one `fmcalc` invocation is valid input to another for pipeline chaining.
