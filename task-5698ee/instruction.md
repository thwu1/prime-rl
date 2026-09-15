A TypeScript EIP-712 typed data processing tool at `/app/` computes signing hashes per the EIP-712 specification. The source files are `eip712.ts` (CLI entry point), `encoder.ts` (type encoding and value serialization), and `hasher.ts` (hash computation). Run with `cd /app && npx tsx eip712.ts [options] < input.json` after `npm install`.

The implementation has correctness bugs -- it produces wrong hashes for valid inputs. Fix all issues so output conforms to the EIP-712 specification.

Extend the CLI to support these modes:

- **No flags**: print one line with the `0x`-prefixed lowercase 66-character signing hash to stdout.

- **`--json`**: print a JSON object to stdout with these exact keys:
  - `signingHash`: `0x`-prefixed final signing hash
  - `domainSeparator`: `0x`-prefixed domain separator hash
  - `messageHash`: `0x`-prefixed message struct hash
  - `primaryType`: the primary type name string
  - `encodeType`: canonical EIP-712 type encoding string for the primary type
  - `typeHash`: `0x`-prefixed type hash for the primary type
  - `referencedTypes`: object keyed by every struct type name referenced by the primary type (excluding `EIP712Domain` and the primary type itself), each value an object with `typeHash` (`0x`-prefixed) and `encodeType` (canonical string for that individual type)

- **`--verify <hash>`**: compute the signing hash, print it to stdout, then exit with code 0 if it matches `<hash>` (case-insensitive comparison), or code 1 otherwise.

**Input format:** JSON with `types` (including `EIP712Domain`), `primaryType`, `domain`, and `message` fields per the EIP-712 TypedData schema.

**Success criteria:** All tests in `/tests/test_state.py` pass.
