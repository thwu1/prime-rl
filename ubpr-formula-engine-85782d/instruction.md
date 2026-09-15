Build a UBPR formula computation engine that parses CDR expression language formulas, ingests multi-format Call Report data (JSON + XBRL), resolves concept dependencies through recursive evaluation, and produces computed bank performance ratios with a SQLite audit database.

Input files at `/app/`:

- `formulas.json` — ~85 UBPR formula definitions with `id`, `desc`, and `formula` fields.
- `call_report_data.json` — Balance-sheet Call Report items (RCON schedule) across 5 quarters, keyed by MDRM code in JSON.
- `xbrl_supplement.xml` — Income-statement (RIAD) and supplemental (RCONA) Call Report items as an XBRL instance document. Contains XML namespace-qualified data elements with `contextRef` attributes referencing period definitions in `xbrli:context` elements. Contexts use both instant periods (for point-in-time items) and duration periods with `startDate`/`endDate` (for year-to-date income items). Data from both JSON and XBRL must be merged; formulas reference all items uniformly as `cc:MDRM_CODE[period]`.
- `config.json` — Report date, form type, annualization rules, output concept list, expression syntax reference.

Required outputs:

**`/app/output/ratios.json`** — JSON mapping each concept ID in `config.json`'s `output_concepts` to its computed value (or `null`), rounded to 4 decimal places. All 25 concepts present. Tolerances: ±0.02 for percentages, ±1.0 for dollar amounts.

**`/app/output/ubpr.db`** — SQLite database with:

Tables:
- `evaluations(concept_id TEXT NOT NULL, eval_date TEXT NOT NULL, value REAL, PRIMARY KEY(concept_id, eval_date))` — One row per formula evaluation including intermediates at historical dates for averaging. Exclude system concepts (`UBPRC752`, `UBPR9999`). ≥80 rows, ≥3 distinct dates.
- `formula_deps(source_id TEXT NOT NULL, target_id TEXT NOT NULL, PRIMARY KEY(source_id, target_id))` — Direct `uc:` concept references from formulas (immediate only). ≥50 edges. No self-dependencies.

View:
- `qoq_trends` — View over `evaluations` with columns: `concept_id`, `eval_date`, `value`, `prior_value` (same concept's value at the chronologically preceding evaluation date, NULL if none), `abs_change` (value minus prior_value), `pct_change` (percentage change from prior; NULL when prior is zero or absent). Ordered by concept_id, eval_date.

Expression language: `IF(cond,t,f)`, `AND(a,b)`, `PCTOFANN(n,d)`, `PCTOF(n,d)`, `CAVG04X(#uc:X)`, `CAVG05X(#uc:X)`, `ExistingOf(a,b)`, arithmetic/comparison operators, concept references (`uc:X[P0]`, `cc:X[P0]`), period offsets (`[-P1Q]`, `[-P1Y]`), `ANN`, `null`, literals. `uc:` = computed concepts; `cc:` = raw Call Report items from either data source. `CAVG04X` averages within calendar year; `CAVG05X` includes prior December. `PCTOFANN(n,d) = (n/d) * ANN * 100`. Division by zero or missing data → `null`.
