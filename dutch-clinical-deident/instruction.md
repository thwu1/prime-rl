The pipeline at `/app/pipeline.py` uses the `docdeid` framework (v1.0.1, pre-installed) to de-identify Dutch clinical notes but is broken: it misses most PHI categories, uses incorrect BSN validation, and produces wrong redaction format.

Create `/app/deidentify.py` that correctly de-identifies all clinical notes in `/app/clinical_notes/` (note_001.txt through note_005.txt) and writes output to `/app/output/`.

## Input Data

- `/app/clinical_notes/` — Dutch clinical notes with embedded PHI
- `/app/patients.json` — Maps note IDs to patient first/last names (Dutch naming with particles: "van", "de", "van der")
- `/app/lookup_data/` — Reference lists: `first_names.txt`, `surnames.txt`, `cities.txt`, `hospitals.txt`, `eponymous_diseases.txt`
- `/app/pipeline.py` — Broken pipeline for reference

## Output Requirements

For each `note_XXX.txt`, produce two files in `/app/output/`:

**`note_XXX_annotations.json`** — JSON array of detected PHI spans:
```json
[{"text": "string", "tag": "string", "start": int, "end": int}]
```
where `original_text[start:end] == text`.

**`note_XXX_redacted.txt`** — Original text with each PHI span replaced by its lowercase tag in brackets (e.g., `[naam]`, `[datum]`).

## PHI Tags

`naam`, `datum`, `bsn`, `telefoonnummer`, `email`, `url`, `locatie`, `instelling`

## Key Constraints

- BSN detection must implement the Dutch elfproef checksum — only 9-digit numbers passing the weighted validation are valid BSNs.
- Disease names in `/app/lookup_data/eponymous_diseases.txt` must never be tagged as person names, even when they contain Dutch name particles (e.g., "Gilles de la Tourette", "syndroom van Cushing").
- Doctor names appearing with titles (dr., prof. dr., drs.) and initials must be detected.
- Dutch date formats include DD-MM-YYYY, DD/MM/YYYY, and written forms like "3 maart 2024".
- Phone numbers include mobile (06-XXXXXXXX), landline (0XX-XXXXXXX), and international (+31) formats.
- Annotations must be non-overlapping; when spans conflict (e.g., "Amsterdam" inside "Amsterdam UMC"), prefer the longer match.