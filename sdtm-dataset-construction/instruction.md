Transform raw clinical trial data from study ECD-2023-0847 (Cobimetinib +/- Vemurafenib in BRAF V600-mutated Erdheim-Chester Disease) into CDISC SDTM-conformant datasets per SDTMIG v3.3.

**Input:** `/app/raw_data/` contains patients.csv, adverse_events.csv, vital_signs.csv, lab_results.csv, drug_exposure.csv, disposition.csv, and protocol_info.json.

**Output:** Write eight conformant CSV files to `/app/sdtm_output/`: dm.csv, ae.csv, vs.csv, lb.csv, ex.csv, ds.csv, ts.csv, suppae.csv.

Key conformance points:
- USUBJID format: `{STUDYID}-{SITEID}-{SUBJID}` (SUBJID = patient_num zero-padded to 3 digits)
- ISO 8601 dates; include collection time as `Thh:mm` where available in source
- Study Day uses RFSTDTC (enrollment date) with "no day 0" convention: date on or after ref yields diff+1; date before ref yields diff (negative)
- AGE: completed years at enrollment date, properly accounting for whether birthday has passed
- Standard CDISC controlled terminology: severity grades 1/2/3 mapped to MILD/MODERATE/SEVERE; seriousness Yes/No mapped to Y/N; outcomes mapped to CT (Recovered to RECOVERED/RESOLVED, Not Yet Resolved or Not Recovered to NOT RECOVERED/NOT RESOLVED, Recovering to RECOVERING/RESOLVING, Fatal to FATAL)
- AEDECOD = uppercase verbatim term
- VSTESTCD per CDISC short codes (Systolic Blood Pressure to SYSBP, Diastolic Blood Pressure to DIABP, Heart Rate to HR, Weight to WEIGHT, Height to HEIGHT); VSBLFL="Y" for Baseline visit rows only
- LB domain: convert results to SI units using conversion factors from protocol_info.json si_conversion_rules; derive LBNRIND (HIGH if above normal_high, LOW if below normal_low, NORMAL otherwise) by comparing source-unit result against provided normal ranges; LBTESTCD mapping: Glucose to GLUC, Creatinine to CREAT, ALT to ALT, Hemoglobin to HGB; round LBSTRESN to 2 decimal places; all baseline labs get LBBLFL="Y"
- EX domain: each raw drug_exposure row becomes one EX record with EXSEQ numbered sequentially per subject; dose modifications produce separate records
- SUPPAE for non-empty body_location values (QNAM=AELOC, QLABEL="Location of Adverse Event", QORIG="CRF")
- TS parameters must include at minimum: SSTDTC, SENDTC, TITLE, SPONSOR, INDIC, PHASE (study dates in ISO 8601)
- Cross-domain consistency: all USUBJIDs must trace back to DM; STUDYID consistent across every domain