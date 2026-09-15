A SWIFT MT103 validation and conversion engine at `/app/` must parse raw FIN-format messages, validate field and cross-field constraints, check STP compliance, and produce both a JSON validation report and an ISO 20022 pacs.008.001.08 XML document for valid messages.

Run: `cd /app && make all`

The `Makefile` orchestrates Java compilation, engine execution, `jq`-based JSON summarization to `/app/output/summary.json`, and `xmllint` schema validation of the XML output. Both the Makefile and Java sources contain bugs.

**Input**: `/app/messages/batch.fin` — messages separated by `$` on its own line. Each is raw FIN text (blocks 1–5). ACK-prepended messages (service ID `21` in block 1) wrap the actual MT103.

**JSON report** `/app/output/report.json`:
```json
[{"index": 0, "reference": "<:20:>", "valid": true, "stp_compliant": false,
  "errors": [{"field": ":XX:", "rule": "RULE_ID", "message": "..."}],
  "settlement_amount": "<decimal>", "settlement_currency": "<3-letter>",
  "sender_bic": "<block1>", "receiver_bic": "<block2>"}]
```

**JSON summary** `/app/output/summary.json`: `jq` projection — array of `{"ref", "valid", "stp", "errors"}` per message where `errors` is the error count.

**XML output** `/app/output/pacs008.xml`: ISO 20022 pacs.008.001.08 document with namespace `urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08`, containing one `CdtTrfTxInf` per valid message. Must pass `xmllint --noout --schema /app/schema/pacs008_subset.xsd`. Mappings: `:20:` → `TxId` + `EndToEndId`; `:32A:` YYMMDD → `IntrBkSttlmDt` as `YYYY-MM-DD` (YY<50 → 20xx, YY≥50 → 19xx); amount → `IntrBkSttlmAmt` with `Ccy` attribute (decimal, no scientific notation); `:71A:` → `ChrgBr` (`SHA`→`SHAR`, `BEN`→`DEBT`, `OUR`→`CRED`); sender/receiver BICs → `InstgAgt`/`InstdAgt` `BICFI`; ordering customer name → `Dbtr/Nm`; beneficiary name → `Cdtr/Nm`. `GrpHdr` must include `SttlmInf/SttlmMtd` = `INGA`.

**Validation rules** (report with field tag and rule ID):
- `:20:` max 16x, no leading/trailing `/`, no `//`
- `:23B:` ∈ {CRED,CRTS,SPAY,SPRI,SSTD}
- `:32A:` valid calendar date, ISO 4217 currency (including XOF/XAF), comma-decimal amount (trailing comma = .00)
- `:50A/F/K:` exactly one; BIC per ISO 9362 (4α+2α+2αn+opt 3αn); IBAN accounts (matching `^[A-Z]{2}\d{2}`) require mod-97 validation
- `:59/59A/59F:` exactly one, same BIC/IBAN rules
- `:71A:` ∈ {BEN,OUR,SHA}
- C1: `:33B:` currency ≠ `:32A:` → `:36:` required
- C2: same currency → `:36:` forbidden
- C3: BEN → no `:71F:`
- C5: SHA → no `:71G:`
- C6: `:72:` lines `/`-prefixed, continuations `//`, code words ≤8 chars
- STP: `{119:STP}` requires `:50A/F:` only, institution fields option A only; violations → `STP_VIOLATION`

Fix all issues so `make all` succeeds and produces correct output.
