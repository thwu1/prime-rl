A warehouse management system's SQLite database at `/app/warehouse.db` has been producing incorrect financial reports. A reporting script at `/app/report.py` was designed to audit various data integrity and financial metrics, generating output at `/app/report_output.json`. External auditors have flagged multiple values in this report as materially incorrect — their preliminary notes are in `/app/auditor_notes.txt`.

Evaluate the report script's methodology against the actual database state. Determine where and why the script produces incorrect results, then produce two files:

1. `/app/corrected_report.json` — A JSON object with the same keys as the original report, but with values that accurately reflect the true state of the database.

2. `/app/error_analysis.json` — A JSON object with the key `correct_keys` containing a sorted list of metric names from the original report whose values were already correct (exact match for integers; within ±0.01 for floats; exact structural and value match for nested objects).

Do not modify the database.