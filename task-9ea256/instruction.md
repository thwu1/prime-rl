Build an end-to-end interoperability pipeline that converts legacy HL7 v2.5.1 ADT_A01 messages to FHIR R4, applies ConceptMap-based terminology translation across both converted and pre-existing FHIR resources, and produces a validated pipeline report.

## Environment

- `/app/hl7_input/*.hl7` — HL7 v2.5.1 ADT_A01 pipe-delimited messages containing legacy ICD-9-CM diagnosis codes in DG1 segments. Messages use standard HL7 v2 encoding: `|` field separator, `^~\&` encoding characters, with escape sequences (`\T\` for `&`, `\S\` for `^`, etc.).
- `/app/mapping_spec.md` — Complete v2 segment/field to FHIR R4 resource/element mapping specification, including data-type conversions (CWE→CodeableConcept, XPN→HumanName, XAD→Address, XTN→ContactPoint, CX→Identifier), segment-level mappings (PID→Patient, PV1→Encounter, NK1→RelatedPerson, DG1→Condition, AL1→AllergyIntolerance, IN1→Coverage), MSH field indexing rules, and coding system URI translation table.
- `/app/bulk_export/*.ndjson` — FHIR Bulk Data Export NDJSON files (Condition, Observation, AllergyIntolerance) with coded elements using legacy or site-specific code systems.
- `/app/conceptmaps/*.json` — FHIR R4 ConceptMap resources defining translation mappings between source and target code systems, including multi-group structures, one-to-many target mappings, equivalence types (equivalent, wider, narrower), and unmapped-code handling modes (provided, fixed).
- `/app/migration_config.json` — Per-resource-type migration rules specifying FHIRPath selectors for identifying which Coding elements to translate, which ConceptMap to apply, whether to preserve or replace source codings, and source/output directory paths.
- `/app/report_schema.json` — JSON Schema (draft-07) defining the required structure for the pipeline report output.

## Deliverables

### `/app/converter.py`
Parses each `.hl7` message from `/app/hl7_input/` and produces a FHIR R4 Transaction Bundle at `/app/output/bundles/<message_control_id>.json`. The converter must correctly handle MSH field indexing (MSH-1 is the field separator character itself; MSH-2 occupies the first value after the segment name when splitting), HL7 escape sequences, repeating fields via `~`, component separation via `^`, and all segment-to-resource mappings defined in `/app/mapping_spec.md`. Each Bundle entry must include `fullUrl` (urn:uuid), `resource`, and `request` (method: POST).

### `/app/migrate.py`
Reads the migration configuration, loads ConceptMap resources, and processes per-resource-type NDJSON files from the configured source directory. Translates targeted Coding elements per the corresponding ConceptMap group, handling: one-to-many mappings (single source code producing multiple target codings), unmapped-code modes (`provided` retains original coding, `fixed` substitutes a designated fallback), the `preserve_source_coding` flag, and passthrough of all non-targeted content.

### `/app/pipeline.sh`
Orchestrates the full pipeline. Must:
- Run the converter on all HL7 v2 messages
- Extract FHIR Condition resources from the generated bundles and consolidate them with the bulk export Condition NDJSON into `/app/staging/Condition.ndjson`. Each extracted resource must have an `id` field. Copy Observation and AllergyIntolerance NDJSON from bulk export to staging.
- Run terminology migration on the staged data
- Produce `/app/output/pipeline_report.json` conforming to the JSON Schema at `/app/report_schema.json`

### Output files
- `/app/output/bundles/CTRL0001.json`, `CTRL0002.json`, `CTRL0003.json` — FHIR R4 Transaction Bundles
- `/app/output/Condition.ndjson` — Migrated Conditions (from both HL7 conversion and bulk export)
- `/app/output/Observation.ndjson` — Migrated Observations
- `/app/output/AllergyIntolerance.ndjson` — Migrated AllergyIntolerances
- `/app/output/pipeline_report.json` — Pipeline report conforming to `/app/report_schema.json`