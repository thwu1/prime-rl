Build `/app/compute_tax.py`. When run via `python3 /app/compute_tax.py`, it must read every `.json` scenario file from `/app/scenarios/`, compute the complete TY2025 Federal income tax return for each, and produce two outputs per scenario:

- **JSON** at `/app/results/{scenario_name}.json` conforming to the JSON Schema at `/app/output_schema.json`
- **XML** at `/app/xml_returns/{scenario_name}.xml` valid against the XSD at `/app/mef_schema.xsd`

All XML files must pass `xmllint --schema /app/mef_schema.xsd --noout` with exit code 0.

IRS TY2025 computation rules — tax rate schedules, worksheet instructions, form line descriptions, credit rules, and employment tax procedures — are provided at `/app/irs_reference/`. These documents are the authoritative source for all rates, thresholds, caps, and computation logic.

Each scenario JSON contains: `filing_status` (`single`/`mfj`/`mfs`/`hoh`/`qss`), `w2s` (array of W-2 records with `wages` and `federal_tax_withheld`), `dividends` (`qualified`, `ordinary`), `capital_gains` (`short_term`, `long_term`), `schedule_h` (household employee wage and withholding fields), and `form_5695` (energy improvement cost fields by category).

**JSON output** must contain exactly the top-level keys `form_1040`, `schedule_d`, `schedule_h`, `form_5695`, `schedule_2`, `schedule_3`. Each maps line identifiers to whole-dollar integers. Required keys, value types, and non-negativity constraints are fully specified in `/app/output_schema.json`. All forms must be present in every result; lines that do not apply are 0.

**XML output** must use the namespace, element structure, ordering, and type restrictions defined in `/app/mef_schema.xsd`. Element values must be consistent with the corresponding JSON result. The XSD enforces element sequence ordering within each form section, type restrictions distinguishing non-negative amounts from signed amounts (capital gains may be negative), a filing-status enumeration, and a fixed tax-year constraint.

The engine must handle all five filing statuses, resolve inter-form dependencies where one form's output feeds into another, and enforce all credit limitations and aggregate caps described in the reference documents. Both `line_34` (refund) and `line_37` (amount owed) must appear in `form_1040`; whichever does not apply is 0.

`python3 /app/compute_tax.py` must exit 0 with correct results for all provided scenarios.
