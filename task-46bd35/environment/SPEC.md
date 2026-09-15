# HMDA Filing Validation Specification

## Filing Format

A HMDA (Home Mortgage Disclosure Act) filing is a pipe-delimited (`|`) text file with the following structure:

- **Line 1**: Transmittal Sheet (TS) record — exactly 15 pipe-separated fields
- **Lines 2+**: Loan Application Register (LAR) records — exactly 110 pipe-separated fields each

Empty/optional fields appear as zero-length strings between pipes. For example, `A||C` contains three fields where the second is empty.

---

## Transmittal Sheet (TS) Fields

The TS record has exactly **15 fields**:

| Field # | Name | Description |
|---------|------|-------------|
| 1 | Record Identifier | Always 1 |
| 2 | Financial Institution Name | Non-empty string |
| 3 | Calendar Year | 4-digit year (e.g., 2024) |
| 4 | Calendar Quarter | Always 4 (annual filing) |
| 5 | Contact Person's Name | Non-empty string |
| 6 | Contact Person's Telephone | Non-empty string |
| 7 | Contact Person's E-mail Address | Non-empty string |
| 8 | Contact Person's Office Street Address | String |
| 9 | Contact Person's Office City | String |
| 10 | Contact Person's Office State | 2-letter state code |
| 11 | Contact Person's Office ZIP Code | String |
| 12 | Federal Agency | Integer code: 1 (OCC), 2 (FRS), 3 (FDIC), 5 (NCUA), 7 (HUD), 9 (CFPB) |
| 13 | Total Number of LAR Entries | Integer — must match actual LAR record count |
| 14 | Federal Taxpayer Identification Number | String |
| 15 | Legal Entity Identifier (LEI) | Alphanumeric, exactly 20 characters |

---

## Loan Application Register (LAR) Fields

Each LAR record has exactly **110 pipe-separated fields**. Fields are numbered 1-110 below. When splitting a LAR line on `|`, field N corresponds to the (N-1)-th element in the resulting zero-indexed array.

| Field # | Name |
|---------|------|
| 1 | Record Identifier (always 2) |
| 2 | Legal Entity Identifier (LEI) — 20 alphanumeric characters |
| 3 | Universal Loan Identifier (ULI) — 23-45 alphanumeric characters, begins with LEI |
| 4 | Application Date — YYYYMMDD or "NA" |
| 5 | Loan Type — 1 (Conventional), 2 (FHA), 3 (VA), 4 (RHS/FSA) |
| 6 | Loan Purpose — 1 (Purchase), 2 (Improvement), 31 (Refinance), 32 (Cash-out refi), 4 (Other), 5 (NA) |
| 7 | Preapproval — 1 (Requested), 2 (Not requested) |
| 8 | Construction Method — 1 (Site-built), 2 (Manufactured) |
| 9 | Occupancy Type — 1 (Principal), 2 (Second), 3 (Investment) |
| 10 | Loan Amount — Numeric, must be greater than 0 |
| 11 | Action Taken — 1 (Originated), 2 (Approved not accepted), 3 (Denied), 4 (Withdrawn), 5 (Incomplete), 6 (Purchased), 7 (Preapproval denied), 8 (Preapproval approved not accepted) |
| 12 | Action Taken Date — YYYYMMDD (must be a valid calendar date) |
| 13 | Street Address |
| 14 | City |
| 15 | State |
| 16 | ZIP Code |
| 17 | County (FIPS code) |
| 18 | Census Tract |
| 19 | Ethnicity of Applicant: 1 |
| 20 | Ethnicity of Applicant: 2 |
| 21 | Ethnicity of Applicant: 3 |
| 22 | Ethnicity of Applicant: 4 |
| 23 | Ethnicity of Applicant: 5 |
| 24 | Ethnicity of Applicant: Free Form Text |
| 25 | Ethnicity of Co-Applicant: 1 |
| 26 | Ethnicity of Co-Applicant: 2 |
| 27 | Ethnicity of Co-Applicant: 3 |
| 28 | Ethnicity of Co-Applicant: 4 |
| 29 | Ethnicity of Co-Applicant: 5 |
| 30 | Ethnicity of Co-Applicant: Free Form Text |
| 31 | Ethnicity Observed — Applicant |
| 32 | Ethnicity Observed — Co-Applicant |
| 33 | Race of Applicant: 1 |
| 34 | Race of Applicant: 2 |
| 35 | Race of Applicant: 3 |
| 36 | Race of Applicant: 4 |
| 37 | Race of Applicant: 5 |
| 38 | Race of Applicant: Free Form — American Indian/Alaska Native Tribe |
| 39 | Race of Applicant: Free Form — Other Asian |
| 40 | Race of Applicant: Free Form — Other Pacific Islander |
| 41 | Race of Co-Applicant: 1 |
| 42 | Race of Co-Applicant: 2 |
| 43 | Race of Co-Applicant: 3 |
| 44 | Race of Co-Applicant: 4 |
| 45 | Race of Co-Applicant: 5 |
| 46 | Race of Co-Applicant: Free Form — American Indian/Alaska Native Tribe |
| 47 | Race of Co-Applicant: Free Form — Other Asian |
| 48 | Race of Co-Applicant: Free Form — Other Pacific Islander |
| 49 | Race Observed — Applicant |
| 50 | Race Observed — Co-Applicant |
| 51 | Sex of Applicant — 1 (Male), 2 (Female), 3 (Not provided), 4 (Not applicable), 6 (Both) |
| 52 | Sex of Co-Applicant |
| 53 | Sex Observed — Applicant |
| 54 | Sex Observed — Co-Applicant |
| 55 | Age of Applicant |
| 56 | Age of Co-Applicant |
| 57 | Income |
| 58 | Type of Purchaser |
| 59 | Rate Spread |
| 60 | HOEPA Status |
| 61 | Lien Status — 1 (First lien), 2 (Subordinate lien) |
| 62 | Credit Score of Applicant |
| 63 | Credit Score of Co-Applicant |
| 64 | Credit Scoring Model — Applicant |
| 65 | Credit Scoring Model Free Form — Applicant |
| 66 | Credit Scoring Model — Co-Applicant |
| 67 | Credit Scoring Model Free Form — Co-Applicant |
| 68 | Reason for Denial: 1 |
| 69 | Reason for Denial: 2 |
| 70 | Reason for Denial: 3 |
| 71 | Reason for Denial: 4 |
| 72 | Reason for Denial: Free Form Text |
| 73 | Total Loan Costs |
| 74 | Total Points and Fees |
| 75 | Origination Charges |
| 76 | Discount Points |
| 77 | Lender Credits |
| 78 | Interest Rate |
| 79 | Prepayment Penalty Term |
| 80 | Debt-to-Income Ratio |
| 81 | Combined Loan-to-Value Ratio |
| 82 | Loan Term |
| 83 | Introductory Rate Period |
| 84 | Balloon Payment |
| 85 | Interest-Only Payments |
| 86 | Negative Amortization |
| 87 | Other Non-Amortizing Features |
| 88 | Property Value |
| 89 | Manufactured Home Secured Property Type |
| 90 | Manufactured Home Land Property Interest |
| 91 | Total Units |
| 92 | Multifamily Affordable Units |
| 93 | Submission of Application |
| 94 | Initially Payable to Your Institution |
| 95 | NMLSR Identifier |
| 96 | Automated Underwriting System: 1 |
| 97 | Automated Underwriting System: 2 |
| 98 | Automated Underwriting System: 3 |
| 99 | Automated Underwriting System: 4 |
| 100 | Automated Underwriting System: 5 |
| 101 | AUS: Free Form Text |
| 102 | AUS Result: 1 |
| 103 | AUS Result: 2 |
| 104 | AUS Result: 3 |
| 105 | AUS Result: 4 |
| 106 | AUS Result: 5 |
| 107 | AUS Result: Free Form Text |
| 108 | Reverse Mortgage |
| 109 | Open-End Line of Credit |
| 110 | Business or Commercial Purpose |

---

## Validation Rules

Implement all rules below. **Violations** (S and V rules) are errors. **Quality flags** (Q rules) are warnings.

### Syntactical Rules

**S300**: The Record Identifier (field 1) must equal `1` for the TS record and `2` for every LAR record.

**S301**: The LEI in each LAR record (field 2) must exactly match the LEI in the TS record (field 15).

**S304**: The Total Number of LAR Entries in the TS (field 13) must equal the actual count of LAR records in the filing.

**S305**: Every LAR record must have a unique ULI (field 3). No two LAR records may share the same ULI value.

### TS Validity Rules

**V600**: The TS LEI (field 15) must be exactly 20 characters in length.

**V601**: The TS Financial Institution Name (field 2) must not be empty.

**V602**: The TS Calendar Year (field 3) must be a 4-digit numeric string.

**V603**: The TS Calendar Quarter (field 4) must equal `4`.

**V604**: The TS Contact Person's Name (field 5) must not be empty.

**V605**: The TS Contact Person's Telephone (field 6) must not be empty.

**V606**: The TS Contact Person's E-mail (field 7) must not be empty.

**V607**: The TS Federal Agency (field 12) must be one of: `1`, `2`, `3`, `5`, `7`, `9`.

### LAR Validity Rules

**V608_1**: The ULI (field 3) must begin with the LEI (field 2) of the same LAR record. The first 20 characters of the ULI must equal the record's LEI.

**V609**: The ULI (field 3) must be between 23 and 45 characters in length (inclusive) and consist only of alphanumeric characters (a-z, A-Z, 0-9).

**V610_1**: The Application Date (field 4) must be either the string `NA` or a valid date in `YYYYMMDD` format. A valid date means the 8-digit string represents a real calendar date (e.g., `20240230` is invalid because February 30 does not exist; `20241345` is invalid because month 13 does not exist).

**V611**: Loan Type (field 5) must be one of: `1`, `2`, `3`, `4`.

**V612_1**: Loan Purpose (field 6) must be one of: `1`, `2`, `31`, `32`, `4`, `5`.

**V613_1**: Preapproval (field 7) must be one of: `1`, `2`.

**V614_1**: Construction Method (field 8) must be one of: `1`, `2`.

**V615_1**: Occupancy Type (field 9) must be one of: `1`, `2`, `3`.

**V616**: Loan Amount (field 10) must be numeric and greater than zero.

**V617**: Action Taken (field 11) must be one of: `1`, `2`, `3`, `4`, `5`, `6`, `7`, `8`.

**V618**: Action Taken Date (field 12) must be a valid date in `YYYYMMDD` format (8 digits representing a real calendar date).

**V619_1**: If Preapproval (field 7) equals `1`, then Action Taken (field 11) must be one of: `1`, `2`, `3`, `4`, `5`, `7`, `8`. (Action `6` — Purchased — is not valid when preapproval was requested.)

**V620**: If Action Taken (field 11) equals `7` or `8`, then Preapproval (field 7) must equal `1`.

**V636_1**: Sex of Applicant (field 51) must be one of: `1`, `2`, `3`, `4`, `6`.

**V661**: Lien Status (field 61) must be one of: `1`, `2`.

### Quality Rules

Quality rules produce informational flags, not rejection errors.

**Q601**: If Loan Amount (field 10) exceeds 10,000,000, flag as a quality concern (unusually large loan amount).

**Q617**: If Application Date (field 4) is a valid date (not `NA`) and Action Taken Date (field 12) is a valid date, and the Action Taken Date is chronologically **earlier** than the Application Date, flag as a quality concern (action taken before application was submitted).
