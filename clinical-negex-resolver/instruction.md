Build a clinical text processing pipeline at `/app/pipeline.py` that extracts medical entities from clinical documents in heterogeneous formats, applies section-aware assertion detection, resolves entities to standardized codes, and produces FHIR-compatible output.

**Inputs:**
- `/app/data/clinical_notes.json` — JSON-format clinical notes with `note_id` and `text` fields
- `/app/data/notes_cda/` — HL7 CDA XML clinical documents with structured sections identified by LOINC codes
- `/app/data/lexicon.db` — SQLite database with an FTS5 virtual table `terms_fts` for medical terminology lookup, alongside relational `terms`, `synonyms`, and `code_systems` tables
- `/app/data/assertion_rules.json` — Trigger phrase categories and scope configuration for assertion detection
- `/app/data/section_config.json` — Clinical document section definitions and processing rules
- `/app/data/fhir_mapping.json` — Assertion-to-FHIR status mappings and entity type filtering rules
- `/app/data/output_schema.json` — JSON Schema defining the required entity output format

The pipeline must parse CDA XML documents using `xmlstarlet` to extract section-structured clinical text (note IDs from `id/@extension`, sections via LOINC-coded `code` elements). Use the FTS5 virtual table for initial candidate entity retrieval, refined by edit-distance similarity (threshold >= 0.85) for fuzzy matching of misspelled terms. Apply section-aware assertion detection where section context establishes default assertion status — explicit assertion triggers in the text always override section defaults. Generate a FHIR-compatible Bundle by invoking `jq` with a custom filter file.

Running `python3 /app/pipeline.py` must produce:
1. `/app/output/results.json` — conforming to the output schema
2. `/app/output/note_texts.json` — mapping `note_id` to the plain text used for offset computation (original text for JSON notes, reconstructed section-concatenated text for CDA notes)
3. `/app/output/summary.csv` — columns `note_id,affirmed,negated,hypothetical,historical` with per-note entity counts
4. `/app/output/fhir_conditions.json` — FHIR Bundle of Condition resources derived from CONDITION and SYMPTOM entities only, generated via `jq` using a filter file the pipeline creates at `/app/fhir_transform.jq`

Character offsets in output must satisfy `note_text[start:end]` yielding the entity text. Examine the database schema, section configuration, assertion rules, FHIR mapping, and CDA document structure to understand the full processing requirements.