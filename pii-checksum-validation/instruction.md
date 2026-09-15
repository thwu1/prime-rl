A partially implemented PII detection and anonymization pipeline built on Microsoft Presidio is at `/app/`. It must detect five PII entity types in a clinical trial corpus and produce **format-preserving anonymized output** where every replacement value passes the same checksum/validation algorithm as the original.

The custom recognizers at `/app/custom_recognizers.py` contain implementation bugs that cause incorrect detection behavior. The checksum algorithm specifications are at `/app/specs/validation_algorithms.md`. Diagnose and fix these issues by comparing the implementations against the specifications.

The pipeline skeleton at `/app/pipeline.py` sets up the detection framework but the `anonymize()` function is not implemented. Design and implement format-preserving anonymization operators for all five entity types:

- **CREDIT_CARD** — Luhn checksum
- **IBAN_CODE** — Mod-97 check digits; country code must be preserved
- **DE_TAX_ID** — ISO 7064 Mod 11,10
- **IT_FISCAL_CODE** — position-dependent check character; structural pattern `[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]` must be preserved
- **DE_HEALTH_INSURANCE** — GKV alternating-multiplier checksum; leading letter + 9 digits format

## Output requirements

- `/app/output/detections.json` — JSON array of objects: `{entity_type, start, end, score, original_value, anonymized_value}`
- `/app/output/anonymized.txt` — corpus with all detected PII replaced by format-preserving anonymized values
- Exactly 3 valid detections per entity type (15 total); the corpus contains deliberately corrupted values that must be rejected
- Each anonymized value must pass its entity type's checksum, match the original's format and length, and differ from the original
- Non-PII text in the anonymized output must be preserved exactly; total text length must not change
- Output must be deterministic when run with seed 42

Run: `python3 /app/pipeline.py --seed 42`