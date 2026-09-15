Five federal court opinions are in `/app/corpus/`. A previous contractor's citation integrity audit (`/app/previous_audit.json`) was rejected: it has wrong court identifiers, incomplete extraction, empty resolution chains, missing cross-document analysis, incorrect authority classifications, and no doctrinal analysis.

Produce a corrected audit at `/app/report.json` conforming to the schema below.

## Schema

- **court_mapping** — Each opinion's authoring court as its canonical CourtListener court identifier (e.g., `"scotus"`, `"ca2"`, `"cafc"`), derived from the opinion header.

- **citations_per_document** — Per document: all full case citations as `[volume, reporter, page]` string triples sorted by volume ascending; counts of `"Id."` and `"supra"` citations.

- **id_resolutions** — Per document: every `"Id."` reference traced to its antecedent full citation, with `id_pin` text and `resolves_to` triple.

- **scotus_shared** — U.S. Supreme Court citations (`"U.S."` reporter) appearing in multiple documents, matched by volume and page. Sorted by volume ascending; each entry lists containing documents.

- **reporter_frequency** — Total full case citations per reporter abbreviation across the corpus. Keys sorted alphabetically.

- **authority_hierarchy** — Per document: each full citation classified by precedential status relative to the citing court. Each entry: citation triple, `cited_court` (canonical court ID derived from reporter and parenthetical attribution), `binding` (boolean). SCOTUS binds all federal courts. Same-circuit published precedent is binding. Sister-circuit is persuasive. Unpublished opinions (F. App'x) are always persuasive.

- **doctrinal_threads** — Chains of cases tracing development of the same legal principle. Each thread: `thread_name`, `cases` (citation triples sorted by volume ascending, minimum 2), `documents` (containing documents). Threads should capture doctrinal progressions described in opinion text.

- **anomalies**:
  - `orphan_id_citations` — `"Id."` references with no traceable antecedent. Fields: `file`, `text`.
  - `court_reporter_mismatches` — Citations where the reporter series implies a different court level than the parenthetical. Fields: `file`, `citation`, `expected_court_type`.
  - `abrogation_risks` — Cases cited in the corpus that have been explicitly abrogated, vacated, or overruled by another case also cited in the corpus. Fields: `abrogated_case` triple, `abrogating_case` triple, `document`, `reason`.

All filenames must be basenames (e.g., `"opinion_001.txt"`).