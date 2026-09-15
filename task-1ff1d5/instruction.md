Raw clinical trial CSV files for study `XYZ001` are in `/app/raw_data/`. Produce CDISC SDTM-conformant datasets per SDTMIG v3.3 and write them as SAS Transport v5 (XPT) files to `/app/sdtm_output/`.

The output schema — variable definitions, controlled terminology codelists, standard units, and structural constraints — is specified in `/app/sdtm_schema.json`. All output datasets must conform to this specification.

## Output Datasets

Write these XPT files to `/app/sdtm_output/`:

| File | Domain |
|------|--------|
| `dm.xpt` | Demographics (DM) |
| `ae.xpt` | Adverse Events (AE) |
| `vs.xpt` | Vital Signs (VS) |
| `ts.xpt` | Trial Summary (TS) |
| `suppae.xpt` | Supplemental Qualifiers for AE (SUPPAE) |

## Conformance Requirements

- All subjects and records in the source data must be represented in the appropriate output domains
- USUBJID format: `XYZ001-{SITEID}-{SUBJID}` with SUBJID zero-padded to 3 digits
- All controlled terminology values must match the codelists specified in the schema exactly (uppercase, exact wording)
- All date/datetime character variables must be in ISO 8601 format
- All variable names must be ≤ 8 characters
- Study day variables follow the no-day-zero convention (RFSTDTC = study day 1)
- Vital signs standardized results (`VSSTRESN`, `VSSTRESU`) must use the standard units per test code defined in the schema; original values and units are preserved in `VSORRES`/`VSORRESU`
- Source data fields that do not correspond to defined SDTM domain variables must be captured in SUPP-- datasets per CDISC supplemental qualifier conventions, with one record per qualifier per parent domain record; QVAL must faithfully preserve the original source data values
- Screen failure subjects must be handled per SDTM conventions across all domains — they appear in DM but must not have treatment-phase reference dates or arm assignments populated
- The VSLOBXFL flag and all derived timing variables must conform to the definitions in the schema
- TS date-type parameters must have their TSVAL in ISO 8601 format; TSSEQ must be sequential starting at 1