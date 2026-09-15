A set of BLE Link Layer packet captures and an HCI-level btsnoop log from a central device require forensic analysis. Audit the captures for protocol compliance against the BLE encryption specification, derive cryptographic session material, and perform a cross-layer security assessment.

## Environment

- Link Layer captures: `/app/captures/ll/*.bllc` (custom binary format)
- Format specification: `/app/format_spec.txt`
- HCI btsnoop log: `/app/captures/hci/central.btsnoop`
- Long Term Key: `/app/ltk.hex`
- BLE encryption procedure reference: `/app/ble_encryption_spec.md`

## Required outputs

All results go in `/app/results/`.

**Per-trace violation report:** For each `.bllc` file, produce `/app/results/<name>.json`:

```json
{
  "trace_file": "<filename>.bllc",
  "total_packets": <int>,
  "violations": [
    {"type": "<TYPE>", "packet_index": <0-based int>, "description": "<text>"}
  ]
}
```

Violation type identifiers: `OUT_OF_ORDER`, `ENCRYPTION_TIMEOUT`, `WRONG_INITIATOR`, `DUPLICATE_PDU`, `TERMINATION_DURING_ENCRYPTION`. Array ordered by `packet_index`. Clean traces get an empty violations array.

**Session keys:** `/app/results/session_keys.json` — map of trace name (without extension) to 32-char lowercase hex session key, only for traces whose encryption procedure completed without any protocol violations.

**Cross-layer security audit:** `/app/results/security_audit.json`:

```json
{
  "findings": [
    {"type": "<FINDING_TYPE>", ...}
  ]
}
```

Finding types and their required fields:
- `KEY_SIZE_REDUCTION`: `connection_handle` (hex string, e.g. `"0x0040"`), `effective_key_size` (int), `trace_file` (string)
- `SKD_REUSE`: `traces` (sorted list of trace filenames)