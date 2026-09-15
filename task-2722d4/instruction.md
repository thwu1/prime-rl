A TypeScript EIP-712 typed structured data hashing tool exists at `/app/`. It reads EIP-712 `TypedData` JSON from stdin and outputs a JSON object with intermediate and final hash values.

The implementation at `/app/src/eip712.ts` contains multiple bugs and missing features that cause incorrect or failing outputs. Fix the implementation to fully comply with the EIP-712 specification (Ethereum typed structured data hashing and signing).

**Setup:** `cd /app && npm install`

**Run:** `echo '<TypedData JSON>' | npx tsx src/cli.ts`

The CLI outputs JSON with fields:
- `encodeType` — canonical type encoding string for `primaryType`
- `typeHash` — `0x`-prefixed hex keccak256 of the `encodeType` string
- `domainSeparator` — `0x`-prefixed hex hash of the `EIP712Domain` struct
- `messageStructHash` — `0x`-prefixed hex hash of the primary message struct (absent when `primaryType` is `EIP712Domain`)
- `signingHash` — the final `0x`-prefixed hex EIP-712 digest

**The full EIP-712 type system must be supported:**
- Atomic types: `bool`, `address`, `uintN` (8–256, step 8), `intN` (8–256, step 8), `bytesN` (1–32)
- Dynamic types: `string`, `bytes` — encoded as `keccak256` of their contents
- Reference types: struct types (by name) and arrays (`Type[]`, `Type[N]`)
- Array values are encoded as `keccak256` of concatenated element encodings
- Struct values are encoded recursively as `hashStruct(value)`

**Recursive types** (e.g., a struct with a field of its own type) are valid type declarations. When a recursive struct field value is `null` or `undefined`, encode it as 32 zero bytes.

**Type dependencies:** `encodeType` lists the primary type first, then all referenced struct types sorted alphabetically. Array field types (e.g., `Person[]`) must resolve the base struct type as a dependency. Diamond-shaped and deeply nested dependency graphs must be deduplicated correctly.

**Value encoding rules:**
- `address`: left-padded to 32 bytes (ABI uint160 encoding)
- `intN`: two's complement sign extension to 256 bits
- `bytesN`: right-padded (zero-filled at the end) to 32 bytes
- `bool`: uint256 0 or 1

**ERC-191 prefix:** `\x19\x01 ‖ domainSeparator ‖ hashStruct(message)`. When `primaryType` is `EIP712Domain`, the message hash component is omitted.

The implementation must not use any external EIP-712 library. Only `js-sha3` for the keccak256 primitive is permitted.

**Success:** `/tests/test.sh` passes all assertions.
