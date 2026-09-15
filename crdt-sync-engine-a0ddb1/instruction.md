A CRDT sync engine skeleton exists at `/app/`. Complete the implementation so the project compiles with `cd /app && npm install && npx tsc` and passes all verification tests.

## Starting state

- `/app/src/types.ts` — shared type definitions (`ID`, `Item`, `DeleteSet`, `StateVector`, `StructStore`, `Update`). Do not modify.
- `/app/src/encoding.ts` — `Encoder`/`Decoder` stubs with only byte-level methods working.
- `/app/package.json` — includes `lib0` as a dependency (the reference implementation of the target binary encoding format, available in `node_modules/lib0` after `npm install`).

## Required files under `/app/src/`

**encoding.ts** — Complete every stub method. The encoding must be wire-compatible with lib0's encoding/decoding modules.

**document.ts** — Export `Doc` class with public readonly `clientID` property. Constructor: `(clientID: number)`. Methods:
- `mapSet(name: string, key: string, value: any)`
- `mapGet(name: string, key: string): any` — returns `undefined` for missing/deleted keys
- `mapDelete(name: string, key: string)`
- `mapEntries(name: string): Map<string, any>` — non-deleted entries only
- `getStateVector(): StateVector`
- `applyUpdate(update: Update)`
- `computeUpdateSince(remoteSV: StateVector): Update`

Concurrent writes to the same map key from different replicas must resolve deterministically and identically on all replicas after sync.

**update.ts** — Exports:
- `encodeUpdate(update: Update): Uint8Array`
- `decodeUpdate(data: Uint8Array): Update`
- `encodeStateVector(sv: StateVector): Uint8Array`
- `decodeStateVector(data: Uint8Array): StateVector`
- `mergeUpdates(updates: Uint8Array[]): Uint8Array` — a merged update applied to an empty doc must produce the same state as applying each input update sequentially.

**sync.ts** — Exports:
- `syncPair(a: Doc, b: Doc)` — full bidirectional sync via binary-encoded state vectors and updates
- `syncAll(docs: Doc[])` — repeated pairwise sync until all documents converge to identical state

**cli.ts** — Export `runCli(args: string[]): string`. Also executable as `node dist/cli.js <cmd> <arg>`. Commands:
- `encode-sv <json>` → hex string
- `decode-sv <hex>` → JSON string
- `roundtrip-any <json>` → encode via `writeAny` then decode via `readAny`, return JSON
- `simulate <json>` → execute scenario, return per-document map state as JSON

Simulate input schema: `{"docs":[id,...],"ops":[{"doc":id,"op":"set","map":m,"key":k,"value":v} | {"doc":id,"op":"delete","map":m,"key":k} | {"op":"sync_pair","docs":[a,b]} | {"op":"sync"}]}`

## Success criteria

`cd /app && npm install && npx tsc` exits 0. All verification tests pass.
