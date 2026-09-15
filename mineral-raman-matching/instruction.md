Build `/app/mineral_id.py` (Python CLI) and `/app/pipeline.sh` (shell orchestrator) for RRUFF mineral spectroscopy analysis. Sample files in `/app/samples/` demonstrate format conventions. All `mineral_id.py` subcommands output JSON to stdout and exit 0 on success.

**`python3 /app/mineral_id.py parse <file>`** — Parse an RRUFF file with `##KEY=VALUE` header lines, a blank-line separator, then CSV data rows (supporting scientific notation). A `##END=` line terminates data. Output `null` for `cell_parameters` and `wavelength` when their respective headers are absent.
Output: `{"names": str, "rruff_id": str, "ideal_chemistry": str, "locality": str, "cell_parameters": {"a","b","c","alpha","beta","gamma","volume": numeric, "crystal_system": str} | null, "filetype": str, "wavelength": int | null, "data_points": int, "wavenumber_range": [min, max]}`

**`classify-crystal <a> <b> <c> <alpha> <beta> <gamma>`** — Classify crystal system from unit cell dimensions (Å) and angles (°) with tolerance for measurement imprecision. Trigonal minerals use the hexagonal cell setting and must classify as `hexagonal`. Output: `{"crystal_system": str}`

**`parse-formula <formula>`** — Parse RRUFF chemical formulas. Notation: `_N_` subscripts; `^N+^` charge annotations (stripped from composition); `_X-Y_` range subscripts (use first value X); `(A,B)` solid solutions (use first component A only); `[box]` prefix (ignored); nested parenthesized groups with multipliers. MW within 0.5 g/mol of IUPAC standard atomic weights. Output: `{"elements": {"Si": 1.0, ...}, "molecular_weight": float}`

**`build-library <source> <output.db>`** — Ingest spectral files from a directory or `.zip` archive into SQLite. Include only processed Raman spectra with intensities normalized to [0,1]. Table `spectra`: columns `name TEXT, rruff_id TEXT, wavelength INTEGER, wavenumbers TEXT, intensities TEXT` — last two store JSON-encoded arrays. The database must be queryable via the `sqlite3` CLI tool.

**`identify <query_file> --library <lib.db> [--top N]`** — Match a query Raman spectrum against the library. Handle both raw (baseline-corrupted) and processed queries. Compare only entries whose excitation wavelength matches the query. A processed spectrum matched against itself must score ≥ 0.99. Output top N (default 5) matches sorted descending by score (0–1): `[{"name": str, "rruff_id": str, "score": float}, ...]`

**`detect-spikes <raw_file>`** — Detect cosmic-ray artifacts in raw Raman data. Clean data must yield `spike_count: 0`. Each spike's `cleaned_intensity` must be a corrected estimate less than 1/10 of `original_intensity`. Output: `{"spike_count": int, "spikes": [{"index": int, "wavenumber": float, "original_intensity": float, "cleaned_intensity": float}]}`

## pipeline.sh

`/app/pipeline.sh <source_dir_or_zip> <query_file> <output.json>`

Orchestrate end-to-end identification: build a temporary SQLite library via `mineral_id.py`, extract library statistics using the `sqlite3` CLI tool, run identification via `mineral_id.py`, and merge all results into `<output.json>` using `jq`. The script must invoke both `sqlite3` and `jq` as external shell commands. Must accept `.zip` archives as source. Output schema:

```json
{"library_stats": {"total_spectra": int, "unique_minerals": [str, ...], "wavelengths": {"532": int, ...}}, "identification": [{"name": str, "rruff_id": str, "score": float}, ...]}
```

`unique_minerals` sorted alphabetically. Wavelength keys are strings. `identification` contains top-5 matches.
