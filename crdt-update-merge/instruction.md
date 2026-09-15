A TypeScript library at `/app/` implements binary encoding, parsing, serialization, merging, and sync-protocol primitives for CRDT update messages in a YATA-based system. The implementation has defects and incomplete functionality across multiple modules.

Binary update format:

- `[numClients: varUint]`, per client (clientID **descending**): `[clientID: varUint] [numStructs: varUint] [firstClock: varUint]`
- Per struct: `[flags: uint8] [length: varUint] [origin?] [rightOrigin?] [parentKey: varString] [content?]`
- Flags: bit 0 = hasOrigin, bit 1 = hasRightOrigin, bits 2-4 = contentType (0=GC, 1=Deleted, 2=String)
- Origin/rightOrigin: `[client: varUint] [clock: varUint]`. String content: `[value: varString]`
- Clocks are sequential within a client: struct N clock = struct N-1 clock + struct N-1 length
- Delete set: `[numClients: varUint]`, per client: `[clientID: varUint] [numRanges: varUint]`, per range: `[clock: varUint] [length: varUint]` -- ranges sorted and consolidated

State vector binary format: `[numEntries: varUint]`, per entry: `[clientID: varUint] [clock: varUint]`. Clock = next expected clock for that client (one past the highest clock covered by any struct).

Source files in `/app/src/`: `encoder.ts`, `decoder.ts`, `types.ts`, `parse-update.ts`, `write-update.ts`, `delete-set.ts`, `merge-updates.ts`, `state-vector.ts`, `cli.ts`, `index.ts`.

Required behavior:

`mergeUpdates(updates: Uint8Array[]): Uint8Array` -- combine multiple binary updates into one containing the union of all structs (deduplicated by clock range per client, sorted by clock) and all delete sets consolidated.

`computeStateVector(update: Update): Map<number, number>` -- map each clientID to its next expected clock as defined above.

`encodeStateVector` / `decodeStateVector` -- binary round-trip state vectors per the format above.

`diffUpdate(update: Update, remoteSV: Map<number, number>): Update` -- return only structs whose clock range covers values beyond the remote's known clock. A struct covers `[id.clock, id.clock + length)`. Delete sets are always included in full.

CLI tool (`node /app/dist/cli.js <command>`):
- `inspect <file>` -- print JSON of a binary update file
- `merge <file1> [file2...] -o <outfile>` -- merge binary update files
- `sv <file>` -- print state vector as JSON
- `diff <update-file> <sv-file> -o <outfile>` -- write update with structs not covered by the state vector

The CLI must correctly handle binary file I/O -- update files contain arbitrary byte values including bytes > 0x7F.

Verify: `/tests/test.sh`
