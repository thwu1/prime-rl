Raw clinical trial data from a Phase II hypertension study (Study XYZ2024) is provided in `/app/raw_data/`. Transform it into six CDISC SDTM-compliant domain datasets conforming to SDTM Implementation Guide v3.3, written as CSV files to `/app/sdtm/`.

## Input

- `/app/raw_data/subj_info.csv` — Subject demographics (MM/DD/YYYY dates, free-text race/ethnicity values)
- `/app/raw_data/adverse_events.csv` — AE records with numeric severity codes (1/2/3), misspelled verbatim terms, missing resolution dates for ongoing events
- `/app/raw_data/vital_signs.csv` — Vital sign measurements with non-standard units (lbs, bpm)
- `/app/raw_data/drug_dosing.csv` — Drug exposure records with non-CT dosing frequency/form values
- `/app/raw_data/medical_dictionary.csv` — Verbatim-to-preferred-term mapping for AE coding (includes body system class)
- `/app/raw_data/protocol_synopsis.txt` — Protocol description for trial summary parameters
- `/app/raw_data/sponsor_conventions.txt` — Sponsor-specific controlled terminology mappings and derivation rules

## Required Output

Write these SDTM domains to `/app/sdtm/`:

- `dm.csv` — Demographics (Special Purpose). Derive AGE from birth date and RFSTDTC. Map race/ethnicity to CDISC CT.
- `ae.csv` — Adverse Events (Events class). Map severity codes to CT (MILD/MODERATE/SEVERE). Code verbatim terms via the medical dictionary. Compute study days using the no-Day-0 rule.
- `vs.csv` — Vital Signs (Findings class). Standardize units (lbs->kg, bpm->beats/min). Populate VSORRES/VSORRESU and VSSTRESC/VSSTRESN/VSSTRESU. VSTESTCD must be <=8 characters.
- `ex.csv` — Exposure (Interventions class). Map dosing frequency to CT (QD) and form to CT (TABLET).
- `suppae.csv` — Supplemental Qualifiers for AE. The non-standard `AE_of_Special_Interest` column must be placed here using SUPP-- structure (RDOMAIN=AE, IDVAR=AESEQ, QNAM=AESIFL).
- `ts.csv` — Trial Summary (Trial Design). Populate from protocol synopsis. Must include SSTDTC, TPHASE, STYPE, TBLIND, RANDOM, and other standard parameters.

All domains must use correct SDTM variable names with domain prefixes, ISO 8601 date formats, and CDISC controlled terminology values throughout.