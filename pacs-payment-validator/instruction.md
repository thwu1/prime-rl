A validator at `/app/validator.py` processes ISO 20022 pacs.008 (FIToFI Customer Credit Transfer) XML messages. It produces incorrect results for certain inputs and is missing required validation rules. The corrected validator must handle all rules below, support all three namespace versions, and produce accurate results for every input.

**Usage:** `python3 /app/validator.py [--format json|ndjson] [--schema-dir <path>] <file.xml|-> [...]`

Passing `-` reads XML from stdin; the result `file` field must be `"<stdin>"`. Default output is a JSON array to stdout. `--format ndjson` emits one JSON object per line with no wrapping array. `--schema-dir` specifies a directory containing XSD files named `pacs.008.001.{VV}.xsd` (default: `/app/schemas/`). When a matching XSD exists, the validator invokes `xmllint --noout --schema` via subprocess and reports failures. If `xmllint` is unavailable or no XSD matches, validation is skipped.

**Output per file:**

```json
{"file": "<path>", "valid": true, "errors": [{"rule_id": "...", "message": "...", "tx_index": null}]}
```

`tx_index`: `null` for group-header errors, 0-based index into `CdtTrfTxInf` for transaction errors. Exit 0 if every file is valid, 1 otherwise.

**Namespaces:** `urn:iso:std:iso:20022:tech:xsd:pacs.008.001.{08,09,10}`

**Required `rule_id` values:**

`XML_PARSE` — malformed XML or missing root. `NS_INVALID` — unsupported namespace. `XSD_SCHEMA_FAIL` — xmllint schema violation. `MSGID_FORMAT` — MsgId exceeds 35 chars, starts/ends with `/`, or contains `//`. `NBOFTXS_MISMATCH` — NbOfTxs ≠ actual count. `TOTAL_AMT_MISMATCH` — TtlIntrBkSttlmAmt ≠ sum of IntrBkSttlmAmt (exact decimal). `TOTAL_AMT_CCY` — total currency ≠ any transaction currency. `IBAN_FORMAT` — fails `^[A-Z]{2}[0-9]{2}[A-Z0-9]+$`. `IBAN_LENGTH` — wrong length per IBAN registry. `IBAN_CHECKSUM` — mod-97 failure. `BIC_FORMAT` — invalid ISO 9362 (8 or 11 chars). `CCY_INVALID` — not in ISO 4217 or undefined minor units. `CCY_EXPONENT` — decimals exceed minor units. `STTLM_DATE_WEEKEND` — settlement on weekend. `STTLM_DATE_HOLIDAY` — settlement on TARGET2 holiday. `AMT_NOT_POSITIVE` — amount ≤ 0. `XCHG_RATE_MISSING` — currencies differ without XchgRate. `XCHG_RATE_NOT_ALLOWED` — same currencies with XchgRate. `INSTG_INSTD_SAME` — identical InstgAgt/InstdAgt BICs. `UETR_FORMAT` — not valid UUID v4. `E2EID_DUPLICATE` — duplicate EndToEndId within message. `STTLM_CLRG_NO_CLRSYS` — CLRG without ClrSys. `STTLM_COVE_NO_AGENT` — COVE without reimbursement agent. `CHRG_BEARER_INVALID` — ChrgBr present but not DEBT, CRED, SHAR, or SLEV. `DBTR_CDTR_SAME_ACCT` — debtor and creditor IBAN identical within a transaction.

**Scope:** IBAN mod-97 with country-specific lengths for 75+ countries on all `IBAN` elements. BIC ISO 9362 on all `BICFI` elements. ISO 4217 minor-unit enforcement. TARGET2 calendar: weekends plus Jan 1, Good Friday, Easter Monday, May 1, Dec 25, Dec 26 (1900–2199). XSD validation via `xmllint`. All reference data embedded.
