Build a UK payroll deduction engine for tax year 2026-27 as an executable at `/app/payroll` (any language). It accepts `--format {json|csv}` and an input file path, writes JSON to stdout, and persists all results to a SQLite database at `/app/payroll.db`.

**Usage**: `payroll --format json input.json` or `payroll --format csv input.csv`

**JSON input schema**:
```json
{"tax_year":"2026-27","employees":[{"id":"string","pay_frequency":"weekly|monthly","ni_category":"A|H|J|M","student_loans":["plan_1"],"periods":[{"period_number":1,"gross_pay":2500.00,"tax_code":"1257L","w1m1":false}]}]}
```

**CSV input**: columns `employee_id,pay_frequency,ni_category,period_number,gross_pay,tax_code,w1m1,student_loans`. Multiple rows per employee grouped by `employee_id`, ordered by `period_number`. `student_loans` is pipe-delimited (e.g. `plan_1|postgraduate`); empty means none. `w1m1` is `true`/`false`.

**JSON output schema**:
```json
{"employees":[{"id":"string","results":[{"period_number":1,"paye":{"tax_due":0.00,"tax_due_to_date":0.00},"nic":{"employee_nic":0.00,"employer_nic":0.00,"total_nic":0.00},"student_loans":{"plan_1":0.00}}]}]}
```

**SQLite output** (`/app/payroll.db`): each run creates/replaces two tables:
- `payroll_results(employee_id TEXT, period_number INT, gross_pay REAL, tax_due REAL, tax_due_to_date REAL, employee_nic REAL, employer_nic REAL, total_nic REAL)` PK `(employee_id, period_number)`
- `student_loan_deductions(employee_id TEXT, period_number INT, loan_type TEXT, deduction REAL)` PK `(employee_id, period_number, loan_type)` -- only for employees with loans

**Specifications** are provided in original HMRC publication formats:
- `/app/specs/ni_guidance.odt` -- NI contributions guidance (OpenDocument Text format)
- `/app/specs/paye_spec.odt` -- PAYE calculation routines (OpenDocument Text format)
- `/app/specs/student_loan_spec.txt` -- Student loan deduction rules (plain text)

**Reference test data** in original HMRC spreadsheet formats at `/app/specs/test_data/`: `.xlsx` for NIC and tax, `.ods` for student loans.

**PAYE income tax**: Implement calculation routines from `paye_spec.odt`. Support suffix codes (e.g. `1257L`), K/SK/CK codes (e.g. `K630`, `SK630`), flat-rate codes `BR`/`SBR`/`CBR`, D codes `D0`/`D1`, and `NT`. Handle Week1/Month1 basis. Support UK, Scottish (`S` prefix), and Welsh (`C` prefix) regimes. Cumulative state carries across code changes. Codes >500 use the split free pay method. Regulatory limit (Maxrate) caps deductible tax.

**NIC**: Implement the exact percentage method for categories A, H, J, M from `ni_guidance.odt`. Both weekly and monthly for A; weekly for H, J, M.

**Student loans**: Plans 1, 2, 4, 5, and Postgraduate per `student_loan_spec.txt`. Per-period thresholds rounded down to the penny. Deductions rounded down to whole pounds. Multiple loans computed independently.

Employee output order must match input order. Include `student_loans` only for employees with assigned loans. All monetary values 2 decimal places. Results must match HMRC expected values within 0.01.
