Build a Rubik's Cube Fewest Moves Challenge (FMC) analysis system that integrates three tools: `sqlite3` for database analytics, the `kociemba` Python package for cube solving, and `jq` for JSON data extraction.

## Data

- `/app/data/fmc_results.tsv` — WCA export of FMC competition results (tab-separated, header row). Columns: `id`, `pos`, `best`, `average`, `competition_id`, `round_type_id`, `event_id`, `person_name`, `person_id`, `format_id`, `regional_single_record`, `regional_average_record`, `person_country_id`.
- `/app/data/fmc_scrambles.tsv` — WCA export of FMC scramble sequences (tab-separated, header row). Columns: `scramble`, `id`, `competition_id`, `event_id`, `group_id`, `is_extra`, `round_type_id`, `scramble_num`.
- `/app/data/target_scrambles.json` — JSON array of 5 scrambles to analyze.

## Deliverables

### 1. SQLite Database (`/app/fmc.db`)

Import the two TSV files into a SQLite database with tables `results` and `scrambles`, preserving column names from the headers. The `best` and `average` columns in `results` must be INTEGER type. Use `sqlite3` CLI or Python's `sqlite3` module.

### 2. Database Statistics (`/app/output/db_stats.json`)

Write the following statistics derived from SQL queries against `/app/fmc.db`. All values must be computed via SQL, not Python post-processing of raw TSV data.

```json
{
  "total_result_rows": <int>,
  "valid_results": <int>,
  "unique_competitors": <int>,
  "unique_competitions": <int>,
  "best_single_ever": <int>,
  "sub20_count": <int>,
  "median_single": <int>,
  "top5_singles": [
    {"person_name": "<str>", "best": <int>, "competition_id": "<str>"},
    ...
  ],
  "records_count": <int>,
  "scramble_count": <int>
}
```

- `valid_results`: rows where `best > 0`.
- `sub20_count`: valid results where `best < 20`.
- `median_single`: median of all valid `best` values.
- `top5_singles`: 5 lowest valid `best` values, ordered ascending by `best` then by `person_name`. Include ties.
- `records_count`: rows where `regional_single_record` is not `'NULL'` and not empty.
- `scramble_count`: total rows in the `scrambles` table.

### 3. Scramble Analysis (`/app/output/scramble_analysis.json`)

For each scramble in `/app/data/target_scrambles.json`, use `jq` to extract the scramble string, then produce:

```json
[
  {
    "competition_id": "<str>",
    "scramble_num": <int>,
    "scramble": "<str>",
    "facelet_string": "<54-char Kociemba facelet string>",
    "kociemba_solution": "<str in Singmaster notation>",
    "kociemba_length": <int>,
    "verified": <bool>,
    "inverse_solution": "<str>",
    "inverse_length": <int>
  },
  ...
]
```

- `facelet_string`: The 54-character Kociemba cube definition string after applying the scramble to a solved cube (`UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB`). Face order is URFDLB, 9 facelets per face in reading order as viewed from outside each face.
- `kociemba_solution`: Solution found by the `kociemba` Python package (`kociemba.solve(facelet_string)`). Convert to standard Singmaster notation (e.g., `R U2 F'` — replace any numeric suffixes like `1` or `3` with `'`).
- `kociemba_length`: Number of moves (space-separated tokens) in the kociemba solution.
- `verified`: True if applying the scramble followed by the kociemba solution to a solved cube yields the solved state.
- `inverse_solution`: The algebraic inverse of the scramble (reverse move order, invert each move).
- `inverse_length`: Move count of the inverse solution.

### 4. Pipeline Script (`/app/pipeline.py`)

A single entry point that produces all outputs. Must use `subprocess` to invoke `sqlite3` for database creation and queries, `jq` for JSON extraction, and the `kociemba` Python library for solving.