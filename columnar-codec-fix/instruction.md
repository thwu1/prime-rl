The project at `/app/` is a TypeScript implementation of encoding primitives from the Automerge columnar binary format, plus a multi-column serializer that composes them. The implementation is incomplete and contains defects.

**Build**: `npm install -g typescript` then `tsc` in `/app/`. Output goes to `/app/dist/`.

**CLI** (`node /app/dist/cli.js <command> <args>`):

Hex I/O uses space-separated lowercase hex bytes. JSON arrays use `null` for nullable entries.

Primitive commands: `encode-uleb`/`decode-uleb`, `encode-sleb`/`decode-sleb`, `encode-rle-uint`/`decode-rle-uint`, `encode-rle-int`/`decode-rle-int`, `encode-delta`/`decode-delta`, `encode-bool`/`decode-bool`.

Column commands: `serialize-columns`/`deserialize-columns`.

**Specification test vectors** (exact byte output required):
- `encode-rle-uint '[0,0,0,null,null,1,2,3]'` → `03 00 00 02 7d 01 02 03`
- `encode-delta '[3,4,5,6,9,7,8]'` → `7f 03 03 01 7d 03 7e 01`
- `encode-bool '[true,true,false,false,false]'` → `00 02 03`
- `serialize-columns '[{"id":3,"type":3,"values":[true,true,false]},{"id":1,"type":2,"values":[1,2,3]}]'` → `02 01 02 02 03 03 03 03 01 00 02 01`

**Column wire format**: A serialized column set begins with a ULEB128 column count. Then, for each column sorted by ascending column ID, a header of three ULEB128 values: column ID, column type (`0`=UINT_RLE, `1`=INT_RLE, `2`=DELTA, `3`=BOOLEAN), and data byte length. After all headers, the column data blocks follow concatenated in the same ID order.

- `serialize-columns` accepts a JSON array of `{"id":number,"type":number,"values":array}` objects
- `deserialize-columns` accepts hex bytes and outputs a JSON array of column objects with `id`, `type`, and `values` fields, sorted by ascending column ID

**Requirements**:
- All encode/decode round-trips must be identity for valid inputs
- Empty arrays encode to empty output; all-null RLE/delta arrays also encode to empty output
- Columns must appear in ascending ID order regardless of input order
- Handle edge cases: empty inputs, single elements, negative signed values, mixed null/non-null patterns, long runs, alternating values
