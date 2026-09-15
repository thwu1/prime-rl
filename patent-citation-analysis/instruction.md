A DuckDB database at `/app/patents.duckdb` contains patent data ingested from multiple feeds. No schema documentation is available — explore the database to discover its tables, columns, and relationships.

The data has not been validated or cleaned. Produce three CSV files in `/app/output/`.

## `data_issues.csv`

Audit the database for data integrity issues. Report each issue category with its count. Columns: `issue`, `count`. Sort: `count` DESC, `issue` ASC.

Check for these categories (exact strings): `self_referencing_citation` (a publication cites itself), `duplicate_citation_edge` (same citing–cited pair appears more than once — count the excess rows), `orphan_citation` (citation references a publication not in the database), `inverted_dates` (grant date precedes filing date), `null_assignee` (publication has no assignee). Include only categories with count > 0.

## `originality_analysis.csv`

Clean the citation graph: remove self-referencing citations, deduplicate edges to one per citing–cited pair, remove orphan citations. For US B2 patents granted 2015 through 2018 with at least 5 cleaned backward citations, compute:

- **Trajtenberg originality index**: 1 minus the Herfindahl concentration index over the 4-character IPC class distribution of the patent's backward-cited publications.
- **Assignee self-citation share**: fraction of cleaned backward citations where the cited publication's assignee matches the focal patent's assignee.

Columns: `publication_number`, `grant_date`, `num_backward`, `num_ipc4_classes`, `originality` (6 decimal places), `self_cite_share` (6 decimal places). Sort: `originality` DESC, `publication_number` ASC. Limit 20 rows.

## `portfolio_ranking.csv`

For the top 10 assignees by patent count (exclude publications with missing assignee), using the cleaned citation graph:

- `tech_diversity`: 1 minus the Herfindahl index of the CPC section distribution across the assignee's patents (6 dp).
- `avg_clean_fwd`: mean cleaned forward citations per patent (4 dp).
- `composite_score`: `0.4 × N(num_patents) + 0.3 × N(tech_diversity) + 0.3 × N(avg_clean_fwd)` where `N(x) = (x − min) / (max − min)` across the 10 assignees; 0 when range is zero. Normalize from full-precision values before rounding (6 dp).

Columns: `assignee`, `num_patents`, `tech_diversity`, `avg_clean_fwd`, `composite_score`. Sort: `composite_score` DESC, `assignee` ASC.