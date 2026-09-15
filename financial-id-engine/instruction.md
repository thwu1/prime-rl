Create `/app/fid_engine.py` — a financial identifier engine that validates, classifies, cross-references, and repairs seven identifier types: IBAN, BIC, LEI, ISIN, CUSIP, FIGI, and SEDOL.

Reference implementations for each type (from python-stdnum, read-only, broken internal imports) are at `/app/vendor/stdnum/`. BBAN structure data for IBAN validation is in `/app/data/iban.dat`, using python-stdnum's numdb data format. Country-specific IBAN lengths must be derived from BBAN token structures (not stated explicitly).

**Usage:** `python3 /app/fid_engine.py /app/data/batch.json /app/data/iban.dat /app/output/identifiers.db /app/output/report.json`

**Input** (`/app/data/batch.json`): JSON array of records, each with `"id"` and optional `"identifiers"` (field-name → value map) and/or `"repair"` (value-with-`?`-placeholders → type-name map).

**Primary output — SQLite database** (`/app/output/identifiers.db`):

- Table `validations`: columns `record_id TEXT, field TEXT, input TEXT, compact TEXT, detected_type TEXT, valid INTEGER, error TEXT`. Compaction normalizes by stripping whitespace/hyphens/dots and uppercasing. `valid` uses 0/1 (SQLite has no native boolean). `error` is NULL when valid, otherwise one of: `invalid_length`, `invalid_format`, `invalid_checksum`, `invalid_component`.

- Table `repairs`: columns `record_id TEXT, input TEXT, type TEXT, repaired TEXT, check_digits TEXT`. `?` characters in the input mark unknown check-digit positions; replace them with the correctly computed digit(s).

- View `cross_references`: columns `record_id TEXT, check TEXT, consistent INTEGER`. This must be a SQL VIEW — cross-reference consistency is computed by the database engine via relational joins on the `validations` table, not pre-populated by application code. Only valid identifier pairs participate. Three checks: `cusip_isin` (ISIN national portion matches CUSIP compact), `sedol_isin` (ISIN national portion matches zero-left-padded SEDOL compact to 9 characters), `iban_bic_country` (IBAN country code matches BIC country-code position).

**JSON report** (`/app/output/report.json`): Exported by querying the database. Object with keys `"validations"`, `"cross_references"`, `"repairs"`, each an array of row objects. In JSON, `valid`/`consistent` are boolean (`true`/`false`); `error` is `null` when absent.

**Auto-detection:** When field name is unrecognized, try validators in order: IBAN, FIGI, ISIN, LEI, BIC, CUSIP, SEDOL. First valid match wins; if none, `detected_type: "unknown"`, `valid: false`.
