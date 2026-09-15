De-identify three Dutch clinical documents at `/app/corpus/` to remove all Protected Health Information (PHI) while preserving medical terminology. The `docdeid` framework (v1.0.1) is pre-installed. Patient metadata is at `/app/patients.json`. Reference data (name lists, places, institutions, medical terms) is in `/app/data/`. A specification with PHI categories and output format is at `/app/spec.md`.

Create `/app/run_pipeline.sh` (and any supporting code in `/app/`) that processes all three documents and writes output to `/app/output/`. For each document, generate:
- `{docname}.txt` — redacted text with `[TAG-N]` placeholders (e.g., `[NAAM-1]`, `[BSN-1]`); identical original strings share the same counter
- `{docname}.annotations.json` — JSON array of annotation objects with `text`, `start_char`, `end_char`, and `tag` fields

The documents contain overlapping and ambiguous PHI that requires domain expertise to resolve correctly:

- BSN (Burgerservicenummer) values must be validated against the official Dutch checksum — the corpus includes both valid and invalid 9-digit sequences, and only verified BSNs should be tagged
- Patient surnames collide with medical eponyms: one patient is named "Henoch" while the disease "Henoch-Schönlein purpura" also appears in the same document — medical terminology must survive de-identification intact
- Dutch multi-word surnames with interfixes ("van der", "de", etc.) and hyphenated married names require compound detection across token boundaries
- PHI spans at least eight categories including names with titles/initials, dates in numeric and Dutch-language formats, phone numbers in domestic and international formats, postal addresses, institutions, and email addresses