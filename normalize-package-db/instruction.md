Three data sources about Python packages are available at `/app/data/`:

- `registry.csv` — Package registry with metadata (author, license, description, etc.) for 15 packages. Authors are in `Name <email>` format; some entries have irregular whitespace (e.g., double-space in a name).
- `downloads.jsonl` — CDN download analytics for 20 packages. Package names use inconsistent casing (e.g., `Flask`, `PyTest`, `HTTPX`). Five packages appear only in this source with no registry metadata.
- `dependencies.json` — Dependency graph mapping package names to their direct dependencies. Includes entries for intermediate packages (e.g., `starlette`, `botocore`) that are not tracked as top-level packages but participate in transitive dependency chains.

Produce a unified, normalized SQLite database at `/app/data/warehouse.db` using `sqlite-utils` (pre-installed). The database must satisfy these requirements:

**Reconciliation**: Match packages across sources by case-insensitive name comparison. Store all names lowercase. The database must contain exactly 20 unique packages — 15 from both sources and 5 from downloads only. Packages only in downloads have NULL for registry-only fields (description, homepage, etc.) but use their `first_seen` value as `first_release`.

**Normalization**: Third Normal Form. Extract authors (parsed from `Name <email>`, whitespace-collapsed so e.g. `"Armin  Ronacher"` becomes `"Armin Ronacher"`), categories, and licenses into lookup tables with integer PKs referenced by FKs from packages. Packages sharing the same normalized author must reference a single row. The packages table must use `id` as INTEGER PRIMARY KEY.

**Data quality**: Dates as `YYYY-MM-DD`, datetimes as `YYYY-MM-DDTHH:MM:SS`. Download counts as integers. Tags as JSON arrays.

**Dependency analysis**: Store direct dependencies in a `dependencies` table (`package_id` FK to packages, `dependency_name` text). Compute each package's `dependency_depth` — the longest transitive chain through the full known dependency graph — and store it on the packages table. Depth 0 means no dependencies; depth N means the longest chain passes through N levels of intermediate dependencies.

**Full-text search**: FTS5 on packages `name` and `description`, porter tokenizer, auto-update triggers.

**Analytics view**: `package_intelligence` view joining all tables, exposing: `id`, `name`, `version`, `author_name`, `author_email`, `category`, `license`, `monthly_downloads`, `daily_avg`, `trend`, `dependency_depth`, `first_release`, `last_update`, `description`, `tags`, `status`, `homepage`.

**Infrastructure**: Indexes on all FK columns. WAL journal mode.