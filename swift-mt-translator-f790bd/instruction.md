Build two tools at `/app/`:

**Translator CLI:** `python3 /app/mt103_to_pacs008.py <input.mt103> <output.xml>` — reads a SWIFT MT103 message file and produces an ISO 20022 CBPR+ envelope. Exit 0 on success, non-zero on error. Output must be well-formed XML (`xmllint --noout` must pass) with `BizMsg` as root element, wrapping:
- `AppHdr` (namespace `urn:iso:std:iso:20022:tech:xsd:head.001.001.03`)
- `Document/FIToFICstmrCdtTrf` (namespace `urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08`)

The translator must correctly handle all MT103 field variants (option letters A/D/F/K), structured and unstructured party formats, correspondent agent chains, regulatory reporting, remittance code words, sender-receiver information routing, time indications, instruction codes, and CBPR+ compliance constraints (BIC normalization, IBAN detection, mandatory element values).

**Validator CLI:** `/app/validate_cbpr.sh <xml_file>` — executable shell script that uses `xmlstarlet sel` for XPath value extraction and `jq` for JSON assembly. Outputs to stdout a JSON object: `{"valid": <bool>, "checks": [{"name": <string>, "pass": <bool>, "value": <string>}, ...]}`. Must verify at minimum: all BICFI and AnyBIC elements are 11 characters, BizSvc value, MsgDefIdr value, NbOfTxs, UETR presence, and EndToEndId presence. Exit 0 when all checks pass, 1 otherwise. Must exit non-zero with `valid: false` for XML lacking required CBPR+ elements.

**Reference materials** at `/app/reference/`: `cbpr_translation_guide.txt`, `cbpr_rules.txt`, `mt103_fields.txt`, `field_mapping.txt`, and `sample_pair/` containing a matched MT103 input with its expected pacs.008 XML output. These documents define the translation rules, field mappings, and CBPR+ compliance requirements your implementation must satisfy.

**Test inputs** at `/app/input/`: `msg_basic.mt103` (IBAN accounts, single currency), `msg_stp_fx.mt103` (STP service, FX with instructed amount, structured parties, charges), `msg_full_chain.mt103` (full correspondent chain with intermediary/reimbursement agents, regulatory reporting, sender-receiver info routing, remittance code words, time indications). All three must translate correctly and pass validation.
