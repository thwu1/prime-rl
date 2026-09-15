A clinical data warehouse at `/app/warehouse.db` (SQLite) was populated from HL7 FHIR R4 NDJSON source files in `/app/fhir_data/` by an ETL pipeline that is no longer available. Clinical analysts report that queries against the warehouse return results inconsistent with the FHIR source data across multiple resource types and fields.

Build `/app/reconcile.py` that audits the warehouse against the FHIR source data, discovers every ETL-introduced discrepancy, and repairs the database. On execution it must:

- Write `/app/audit_report.json` — a structured report listing every discrepancy found, each with its resource identifier, discrepancy category, and expected vs. actual values. Include a `summary` object with a `total_discrepancies` count and per-category breakdowns.
- Repair `/app/warehouse.db` in place so all records accurately reflect the authoritative FHIR source.

The FHIR dataset contains 8 resource types across 5 patients. The warehouse schema, table structures, and FHIR resource models must be inferred from the data. CLI tools `jq` and `sqlite3` are available for investigation. Note that some referential integrity issues in the FHIR source data are inherent data characteristics (not ETL bugs) and should not be "fixed" in the warehouse.