A NACHA ACH file processing pipeline at `/app/` reads `.ach` files from an input directory, validates entries against NACHA ODFI rules, merges all batches into a single output, and produces a JSON validation report.

Usage: `go build -o /app/achpipe . && /app/achpipe --input <dir> --output <file> --report <json-file>`

**Merged output** must conform to NACHA Operating Rules:

- Every record is exactly 94 characters. Record types: File Header (`1`), Batch Header (`5`), Entry Detail (`6`), Addenda (`7`), Batch Control (`8`), File Control (`9`).
- Batch numbers reassigned sequentially from 1. Both Batch Header and Batch Control carry the same batch number (positions 88-94).
- Batch Control recomputation: `EntryAddendaCount` (positions 5-10) counts all Entry Detail and Addenda records. `EntryHash` (positions 11-20) sums the 8-digit Receiving DFI Identification (positions 4-11 of each Entry Detail), truncated to 10 least-significant digits. `TotalDebit`/`TotalCredit` (positions 21-32, 33-44): credit codes have second digit in {1,2,3,4}; debit codes have second digit in {6,7,8,9}. `ServiceClassCode`, `CompanyIdentification`, `ODFIIdentification` preserved from original Batch Header.
- File Control: `BatchCount`, `BlockCount` (ceiling of total records including padding divided by 10), `EntryAddendaCount`, `EntryHash` (sum of batch hashes truncated to 10 digits), `TotalDebit`, `TotalCredit`. Pad with all-9s records until total line count is a multiple of 10.

**Validation** checks each Entry Detail and its context:

- **Check digit**: 9-digit routing number (positions 4-12) must pass the ABA modulus-10 algorithm -- weights `[3,7,1,3,7,1,3,7,1]` applied to each digit, weighted sum divisible by 10.
- **Service class code consistency**: SCC `220` permits credits only, `225` debits only, `200` permits both.
- **Amount range**: entry amount (positions 30-39) must not exceed 2,500,000,000 (i.e. $25,000,000.00).
- **Duplicate trace numbers**: no two Entry Detail records in the same batch may share a trace number (positions 80-94).
- **Trace ODFI prefix**: the first 8 characters of each entry's trace number (positions 80-87) must equal the batch's ODFI Identification (positions 80-87 of the Batch Header).
- **Addenda indicator consistency**: Entry Detail addenda record indicator (position 79) must be `1` if Addenda records immediately follow the entry, `0` otherwise.
- **Addenda sequence ordering**: Type 05 Addenda sequence numbers (positions 84-87) must be sequential starting from 1 for each parent Entry Detail.

**JSON validation report schema:**
```json
{
  "files_processed": 0, "total_batches": 0, "total_entries": 0,
  "errors": [{"error_code": "<CODE>", "batch_number": 0, "entry_sequence": 0, "field": "", "message": ""}],
  "valid": true
}
```
Error codes: `CHECKDIGIT`, `SCC_MISMATCH`, `AMOUNT_RANGE`, `DUPLICATE_TRACE`, `TRACE_ODFI`, `ADDENDA_IND`, `ADDENDA_SEQ`. `valid` is `true` when `errors` is empty.

The current implementation compiles and runs but produces incorrect output in both the merged file and the validation report. Identify and fix all defects across the codebase.
