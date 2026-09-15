# Yjs V1 Binary Wire Format Specification

This document describes the Yjs V1 binary encoding format for update messages and state vectors.

## 1. Primitive Encodings

### 1.1 Variable-Length Unsigned Integer (VarUint)

Encodes non-negative integers using 7 bits per byte, with the MSB as a continuation flag.

- Read bytes one at a time
- For each byte: the low 7 bits contribute to the value, shifted left by `7 * byteIndex`
- If the MSB (bit 7) is set, read another byte; otherwise, stop

Examples:
- `0` → `[0x00]`
- `127` → `[0x7F]`
- `128` → `[0x80, 0x01]` (128 = 0 + 128*1)
- `300` → `[0xAC, 0x02]` (300 = 44 + 128*2)

### 1.2 Variable-Length String (VarString)

- Encode the string as UTF-8 bytes
- Write the byte length as a VarUint
- Write the UTF-8 bytes

### 1.3 Uint8

A single unsigned byte (0–255).

## 2. V1 Update Message Format

A V1 update message is a byte sequence consisting of two sections:

```
[Structs Section] [Delete Set Section]
```

### 2.1 Structs Section

```
numClients: VarUint     — number of distinct client groups
```

For each client group (written in DESCENDING client ID order):

```
numStructs: VarUint     — number of structs for this client
clientID:   VarUint     — the client's ID
firstClock: VarUint     — clock value of the first struct
```

Then `numStructs` structs follow sequentially. Each struct's clock is implicitly tracked: it starts at `firstClock` and increments by each struct's content length.

### 2.2 Struct Encoding

Each struct begins with an **info byte** (Uint8):

```
Bits 0–4 (mask 0x1F): content type reference
  0  = GC (garbage collected placeholder)
  1  = Deleted content
  4  = String content
  10 = Skip (gap placeholder)

Bit 5 (0x20): parentSub is non-null
Bit 6 (0x40): has originRight (right origin reference)
Bit 7 (0x80): has origin (left origin reference)
```

#### GC (content type 0)

```
info:   Uint8 (bits 0–4 = 0)
length: VarUint
```

#### Skip (content type 10)

```
info:   Uint8 (bits 0–4 = 10)
length: VarUint
```

#### Items (content types 1–9)

After the info byte:

**1. Origin references (conditional)**

If bit 7 is set (has origin / left reference):
```
originClient: VarUint
originClock:  VarUint
```

If bit 6 is set (has originRight / right reference):
```
rightOriginClient: VarUint
rightOriginClock:  VarUint
```

**2. Parent info (conditional — only when NEITHER origin NOR originRight is set)**

When an item has no origin and no originRight, it must encode its parent explicitly:

```
parentIsKey: VarUint   — 1 = parent is a root type by name, 0 = parent is by ID
```

If `parentIsKey == 1`:
```
parentKey: VarString   — name of the root type (e.g., "t" for getText("t"))
```

If `parentIsKey == 0`:
```
parentClient: VarUint
parentClock:  VarUint
```

If bit 5 is set (has parentSub):
```
parentSub: VarString
```

**3. Content payload (depends on content type)**

Content type 1 — Deleted:
```
length: VarUint   — number of deleted clock positions
```

Content type 4 — String:
```
string: VarString — the text content (may be multi-character for compound items)
```

### 2.3 Delete Set Section

```
numClients: VarUint
```

For each client:
```
clientID:   VarUint
numRanges:  VarUint
```

For each range:
```
clock:  VarUint   — start clock of deleted range
length: VarUint   — number of consecutive deleted clocks
```

## 3. State Vector Format

```
numClients: VarUint
```

For each client:
```
clientID: VarUint
clock:    VarUint   — next expected clock (one past the max clock seen)
```

## 4. YATA Conflict Resolution (High-Level)

When integrating a remote item, its `origin` (left reference at creation time) and `originRight` (right reference at creation time) determine where it was originally positioned. If no other items have been inserted between origin and originRight since creation, the item is placed directly. Otherwise, the YATA algorithm resolves the conflict:

1. Start scanning from the item after `origin` (or the start of the text if origin is null).
2. For each existing item `o` between origin and originRight:
   - If `o` has the same origin as the new item: the item with the lower `clientID` goes first. If they also share the same originRight, stop scanning.
   - If `o`'s origin is found among previously scanned items but not among conflicting items: `o` goes first.
   - Otherwise: stop scanning.
3. The new item is inserted after the last item that was determined to "go first."

Items with the same origin are ordered by ascending client ID. This ensures all replicas converge to the same document state regardless of the order updates are applied.

For the precise algorithm, consult the `integrate` method in the Yjs source at `/app/node_modules/yjs/dist/yjs.mjs`.

## 5. Compound Items

Yjs optimizes storage by merging consecutive characters from the same client into a single item (compound representation). A compound item with content "hello" has `length = 5` and occupies clock positions `[clock, clock+5)`. When another item references a clock in the middle of a compound item (via origin or originRight), the compound item must be split at that position.
