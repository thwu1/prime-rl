Build `/app/cifcheck.py` and `/app/cifbatch.sh`.

**Provided data files in `/app/`:**
- `check_rules.dat` — Alert rule definitions with inline format documentation. Must be re-read on each invocation; editing thresholds, adding, or removing rules must change output without any code changes.
- `element_weights.cif` — Atomic weights in CIF format. Must be re-read on each invocation; editing weights must change computed molecular weight without code changes.
- `cif_core_subset.dic` — CIF core dictionary subset using DDLm `save_` frame constructs. Must be parsed to build a set of recognized CIF data-item names for dictionary validation.

**`cifcheck.py`:** `python3 /app/cifcheck.py <cif_path>` — parses the input CIF file, implements every validation check defined in `check_rules.dat`, and writes JSON to stdout:

```json
{"data_block": "<name without data_ prefix>",
 "alerts": [{"code":"<3-digit>","level":"<A|B|C>","type":<int>,"message":"<string>","value":<number>,"atom":<string|null>}],
 "computed": {"cell_volume":<float>,"formula_weight":<float>,"density":<float>,"ueq":{"<label>":<float>}}}
```

Requirements:
- Per-atom alerts set `"atom"` to the atom label; structure-level alerts set `null`.
- Empty `alerts` array when no checks fire. Skip a check gracefully when required CIF data items are absent.
- CIF numeric values may include parenthesized standard uncertainty notation (e.g. `5.102(10)`).
- All computed crystallographic quantities must be correct for arbitrary unit cells, including non-orthogonal (monoclinic, triclinic) systems.
- The program must exit 0 on success.

**`cifbatch.sh`:** `bash /app/cifbatch.sh <directory>` — validates every `.cif` file in the given directory by running `cifcheck.py` on each. Must use `jq` to extract per-file fields from JSON output and `sqlite3` to store results.

**Database** at `/app/validation.db`, table `results` with columns: `filename TEXT`, `data_block TEXT`, `alert_count INTEGER`, `max_severity TEXT`, `cell_volume REAL`, `formula_weight REAL`, `density REAL`, `alerts_json TEXT`. `max_severity` is the highest alert level among alerts for that file (`A` > `B` > `C`), or `NONE` when no alerts exist.

**Stdout summary (JSON):**
```json
{"total_files":<int>,"files_with_alerts":<int>,"alert_counts":{"A":<int>,"B":<int>,"C":<int>}}
```
