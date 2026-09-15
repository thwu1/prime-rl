A healthcare organization needs to de-identify FHIR R4 clinical data before sharing it for research. Build a pipeline that applies the anonymization rules defined in a configuration file to all input resources, producing correctly de-identified output that preserves referential integrity and complies with HIPAA Safe Harbor requirements.

The anonymization configuration is at `/app/config.json`. Input FHIR resources are at `/app/input/`. Reference materials from a production implementation are at `/app/reference/`.

Build an executable pipeline at `/app/pipeline.sh` that processes all input files according to the configuration and writes results to `/app/output/`:

- Anonymized versions of each input file, preserving original filenames, resource ordering, and line counts.
- `crypto_manifest.json` — a JSON document with a top-level `verifications` array. Each entry covers one processed resource and must include: `source_file`, `resource_type`, `original_id`, `hashed_id`, `openssl_output` (hash independently recomputed using `openssl`), and `verified` (boolean).