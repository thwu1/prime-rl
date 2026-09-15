A partial TypeScript implementation of the Automerge binary document format's columnar encoding layer exists at `/app/src/codec.ts`. The module provides correct LEB128 integer encoding primitives but its higher-level codec functions are either incomplete (stub functions that throw `Error`) or contain specification-compliance bugs producing incorrect binary output.

The Automerge binary format specification excerpt at `/app/spec-reference.md` defines the correct encoding rules with worked examples and exact byte sequences.

Complete and fix `/app/src/codec.ts` so every exported function produces byte-exact output conforming to the specification. Do not change function signatures or add new exports.

Run `npm install` in `/app` to install dependencies before working with the code. Execute TypeScript with `npx tsx <file.ts>` from `/app`.

**Expected interfaces (do not change):**

- `encodeULEB128(value: bigint): Uint8Array`
- `decodeULEB128(data: Uint8Array, offset?: number): [bigint, number]`
- `encodeLEB128(value: bigint): Uint8Array`
- `decodeLEB128(data: Uint8Array, offset?: number): [bigint, number]`
- `rleEncode(values: (bigint | null)[], encodeValue: (v: bigint) => Uint8Array): Uint8Array`
- `rleDecode(data: Uint8Array, decodeValue: (d: Uint8Array, o: number) => [bigint, number]): (bigint | null)[]`
- `deltaEncode(values: bigint[]): Uint8Array`
- `deltaDecode(data: Uint8Array): bigint[]`
- `booleanEncode(values: boolean[]): Uint8Array`
- `booleanDecode(data: Uint8Array): boolean[]`
- `stringEncode(values: (string | null)[]): Uint8Array`
- `stringDecode(data: Uint8Array): (string | null)[]`
- `encodeColumnSpec(id: number, type: number, deflate: boolean): number`
- `decodeColumnSpec(spec: number): { id: number; type: number; deflate: boolean }`
- `encodeValueMetadata(type: number, length: number): bigint`
- `decodeValueMetadata(value: bigint): { type: number; length: number }`
- `computeChecksum(chunkType: number, chunkLengthBytes: Uint8Array, chunkContents: Uint8Array): Uint8Array`
- `constructChunk(chunkType: number, chunkContents: Uint8Array): Uint8Array`
- `parseChunkHeader(data: Uint8Array): { chunkType: number; checksum: Uint8Array; chunkLength: bigint; headerSize: number; valid: boolean }`
- `createEmptyDocument(): Uint8Array`

**Success criteria**: All tests pass when `/tests/test.sh` is executed.
