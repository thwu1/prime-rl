`/app/resolver.py` processes court database queries from `/app/queries.jsonl` using the `courts-db` package (v0.10.27, pip-installable) and writes results to `/app/results.json`. The resolver contains multiple bugs causing incorrect output for many queries.

Diagnose every defect, understand the courts-db library's data model and API semantics by examining its installed source, and produce a corrected `/app/court_analyzer.py` that handles all queries correctly.

Each query has `id` (integer) and `type` fields plus type-specific parameters. `/app/results.json` must be a JSON object mapping string query IDs to result objects.

Query types, their input fields, and result schemas:

- `resolve` (`text`, `bankruptcy`, `date`, `location`) → `{"court_ids": [sorted strings]}`
- `temporal_status` (`court_id`, `date`) → `{"active": bool, "matching_range": {"start": str|null, "end": str|null}|null}`
- `temporal_gaps` (`court_id`) → `{"gaps": [{"start": str, "end": str}, ...]}`
- `hierarchy` (`court_id`) → `{"ancestors": [strings], "descendants": [sorted strings]}`
- `collisions` (`name`) → `{"courts": [{"id": str, "location": str}, ...sorted by id]}`

Production command: `python3 /app/court_analyzer.py`

Success criteria: `/app/results.json` produces correct results for all 47 queries as verified by the automated test suite.
