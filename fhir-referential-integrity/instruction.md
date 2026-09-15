`/app/data/bundle.json` contains a FHIR R4 bundle with 18 interlinked hospital records (patients, practitioners, organizations, encounters, observations, claims, conditions, medications, allergies, coverage) and 32 cross-resource references containing protected health information.

De-identify this dataset per HIPAA Safe Harbor §164.514(b)(2)(i). All compliance requirements, algorithm specifications, and anonymization parameters are in `/app/requirements.md`.

Produce:

- **`/app/config.json`** — Anonymization configuration conforming to the schema in `/app/requirements.md`.
- **`/app/anonymize.py`** — Anonymization engine that reads the bundle and configuration and writes de-identified output to `/app/output/anonymized.json`.
- **`/app/validate.sh`** — Independent compliance scanner that writes a JSON report to `/app/output/phi_scan.json` with boolean fields: `ids_valid`, `references_valid`, `names_clean`, `contacts_clean`, `addresses_clean`, `hash_verified`.

The de-identified output must preserve clinical utility (organization names, diagnosis text, observation values, medication names), maintain referential integrity across all 32 cross-resource reference chains, and contain zero residual PHI. A single un-hashed reference, leaked name, or inconsistent ID constitutes a compliance failure.