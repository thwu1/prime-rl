Legal predicates—factual assertions from judicial opinions—are provided across two data sources:

- `/app/holdings.yaml` — YAML file containing predicate definitions organized by judicial opinion, including templates, quantity comparisons (with physical units), and truth values
- `/app/terms.db` — SQLite database containing entity term assignments (`predicate_terms` table) and interchangeable position group declarations (`interchangeable_groups` table) for each predicate

A semantic reference describing comparison rules is at `/app/spec.md`.

Your task: integrate data from both sources and classify every pair of predicates as equivalent, strictly-implies, contradicts, or unrelated. Physical unit conversions must use the `pint` library's unit registry—do not hard-code conversion factors.

Write results to `/app/results.json`:

```json
{
  "equivalent": [["ID_A", "ID_B"], ...],
  "implies": [["ID_A", "ID_B"], ...],
  "contradicts": [["ID_A", "ID_B"], ...]
}
```

AND to `/app/results.db` as a SQLite database with table `relationships(id_a TEXT, id_b TEXT, relation TEXT)`.

- `equivalent`: unordered pairs (each sorted alphabetically) where implication holds in both directions
- `implies`: ordered pairs `[A, B]` where A strictly implies B (not vice versa); exclude equivalences
- `contradicts`: unordered pairs (each sorted alphabetically)

Sort all three lists lexicographically. Omit unrelated pairs.