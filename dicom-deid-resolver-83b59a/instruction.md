The environment at `/app/data/` contains:

- `action_table.tsv`: DICOM PS3.15 Table E.1-1 in tab-separated format — 656 attributes with de-identification action codes across the Basic Profile and 10 named options. Column headers use abbreviated option names.
- `spec_normative.txt`: Normative definitions of action codes, compound code semantics, and option descriptions from PS3.15 Annex E.

Create `/app/deid_tool.py` implementing four subcommands:

**resolve**: `python3 /app/deid_tool.py resolve --tag TAG [--options OPT1,OPT2,...] [--iod-type {1,2,3}]`

Print JSON `{"tag": TAG, "resolved_action": ACTION, "source": SOURCE}`. SOURCE is `"basic_profile"` or the overriding option name. Unknown tags return `null` for both fields. TAG format: `(GGGG,EEEE)` uppercase hex. Compound actions without `--iod-type` output unchanged.

**batch-resolve**: `python3 /app/deid_tool.py batch-resolve --options OPT1,OPT2,... [--iod-type {1,2,3}]`

Print JSON array of `{"tag", "attribute_name", "resolved_action", "source"}` for all 656 table entries.

**deidentify**: Two mutually exclusive modes. Single-file: `--input FILE --output FILE`. Dataset: `--input-dir DIR --output-dir DIR`. Both require `--options OPT1,OPT2,... --iod-type {1,2,3}`.

Apply resolved actions: X=remove, Z=zero-length value, D=non-zero-length VR-consistent dummy, U=internally consistent UID remap (same original UID always maps to same replacement, including across all files in dataset mode), K=keep, C=keep. Set `Patient Identity Removed` (0012,0062) to `"YES"` and `De-identification Method` (0012,0063) to non-empty string in each output file. Skip wildcard tag patterns. Per PS3.15 E.1, all actions apply recursively into Sequence (SQ) attribute items—tags from Table E.1-1 embedded within sequence items must be de-identified identically to top-level tags. Output valid DICOM readable by pydicom. Single-file prints `{"status": "ok", "output": PATH}`. Dataset prints `{"status": "ok", "files_processed": N}`.

**audit**: `python3 /app/deid_tool.py audit --input DICOM_FILE --options OPT1,OPT2,... --iod-type {1,2,3}`

Check compliance for each table attribute whose resolved action imposes a deterministic constraint, including recursively within Sequence items. Report `{"violations": [...], "total_checked": N}`. Violation: `{"tag", "attribute_name", "expected_action", "finding", "location": "top_level"|"sequence"}`. Findings: `"present_but_should_be_removed"` (X), `"non_empty_but_should_be_zeroed"` (Z), `"empty_but_should_have_dummy"` (D—present with zero-length value). Skip wildcard tag patterns.

Valid `--options`: `clean_descriptors`, `clean_graphics`, `clean_structured_content`, `retain_full_dates`, `retain_modified_dates`, `retain_patient_chars`, `retain_device_id`, `retain_uids`, `retain_safe_private`, `retain_institution_id`. When multiple options override the same attribute, last listed wins. Map TSV abbreviated column headers to these canonical names. Compound code resolution with `--iod-type` must conform to `spec_normative.txt`.
