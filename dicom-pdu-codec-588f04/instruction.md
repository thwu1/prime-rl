A partial DICOM Upper Layer PDU codec exists at `/app/dicom_codec.py`. It contains defects in its decode and encode paths and is missing several functions. Fix all defects and complete the implementation so the full test suite passes.

A capture generation script at `/app/gen_captures.py` can create binary capture files at `/app/captures/` for inspection.

**Required API** (importable as `from dicom_codec import ...`):

`decode_pdu(data: bytes) -> dict` — Parse one PDU from raw bytes. Handles types 0x01–0x07 per DICOM PS3.8 §9.3. Wire format: 1-byte type, 1-byte reserved, 4-byte big-endian length, then type-specific body.

`encode_pdu(pdu: dict) -> bytes` — Inverse of decode. Round-trip invariant: `encode_pdu(decode_pdu(b)) == b` for well-formed inputs with zeroed reserved fields.

`negotiate_roles(req_scu, req_scp, acc_scu, acc_scp) -> tuple[bool,bool,bool,bool]` — SCP/SCU Role Selection Negotiation per PS3.8 Annex D. Each parameter is `bool | None`. Returns `(requestor_scu, requestor_scp, acceptor_scu, acceptor_scp)`. Default when neither side proposes: requestor=SCU-only, acceptor=SCP-only.

`fragment_pdata(pdvs: list[dict], max_pdu_length: int) -> list[bytes]` — Assemble PDVs into P-DATA-TF PDUs within `max_pdu_length` (0 = unlimited). Split large PDV data across fragments with `is_last=False` on all but the final fragment.

`analyze_stream(filepath: str) -> dict` — Parse a capture file. Auto-detect framing:
- **Raw**: PDUs concatenated directly (first byte is valid PDU type 0x01–0x07).
- **Timestamped**: each PDU preceded by 8 bytes (4-byte big-endian epoch seconds + 4-byte big-endian PDU byte count).
- **PCAP**: standard libpcap capture file (magic `0xa1b2c3d4` or big-endian variant). Extract DICOM PDU payloads from the reassembled TCP stream and decode them. Must handle PDUs that span multiple TCP segments.

Return:
```json
{"framing": "raw"|"timestamped"|"pcap", "pdu_count": N,
 "pdus": [{"offset": int, "pdu_type": int, "pdu_type_name": str,
            "length": int, "timestamp": float_or_null,
            "violations": [str], "decoded": dict}],
 "violation_summary": {"NONZERO_RESERVED": N, "UID_TOO_LONG": N}}
```
`offset` = byte position of PDU type byte (within file for raw/timestamped, within reassembled stream for PCAP). Violation codes: `NONZERO_RESERVED` — reserved byte non-zero; `UID_TOO_LONG` — any parsed UID exceeds 64 characters.

**CLI**: `python3 /app/dicom_codec.py <capture_file>` outputs analysis as JSON to stdout.

**Key dict structures**:
- A-ASSOCIATE-RQ/AC: `pdu_type, protocol_version, called_ae_title, calling_ae_title, application_context, presentation_contexts, user_info`
- P-DATA-TF: `pdu_type, pdvs: [{context_id, is_command, is_last, data}]` — MCH: bit 0 = command, bit 1 = last
- A-ASSOCIATE-RJ/A-ABORT: `pdu_type, result|source, reason`
- A-RELEASE-RQ/RP: `pdu_type` only

AE titles: 16-byte space-padded on wire, trailing-space-stripped on decode. All multi-byte integers: big-endian.
