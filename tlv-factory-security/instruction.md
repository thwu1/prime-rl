Implement a Python CLI tool at `/app/tlv_manager.py` that manages secure factory data for embedded devices using a custom Tag-Length-Value binary format with cryptographic signing, device-binding, and security policy enforcement.

The tool must support these subcommands:

- `encode` — Encode JSON data into a TLV binary blob according to a YAML schema
- `decode` — Decode a TLV binary blob back to JSON, with optional signature verification and device-binding checks
- `sign` — Sign an unsigned TLV blob with an ECDSA-P256 private key
- `verify` — Verify a signed TLV blob against a public key
- `policy-filter` — Decode a blob through a security policy that controls field visibility and enforces signing/binding requirements
- `policy-transition` — Validate whether transitioning between two named security policies is permitted

The binary format uses a 16-byte little-endian header (magic, version, flags, payload length, CRC-32), followed by a payload of tag-length-value entries (each with uint16 tag, uint16 length, variable value), and an optional DER-encoded ECDSA-P256/SHA-256 signature block. Field types include `string`, `mac` (6-byte), `hex`, `uint16`, `uint32`, and `binary` (base64 in JSON). The complete specification, CLI interface contract, exit codes, and policy semantics are in `/app/spec.md`.

Test schemas are at `/app/schemas/factory_board_v1.yaml`, security policies at `/app/policies/`, and an ECDSA P-256 keypair at `/app/test_keys/`.