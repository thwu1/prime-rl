`/app/FORMAT.md` specifies a custom binary file format for a persistent B+tree key-value store. The format uses fixed-size 4096-byte pages: a meta page (page 0) with a root pointer, page count, and CRC-32 checksum, followed by B+tree node pages using a compact binary layout of type/nkeys/pointers/offsets/kv-data.

Six database files in `/app/databases/` exhibit various integrity issues — invalid checksums, dangling child pointers, leaf key sort violations, orphaned (unreachable) pages, and corrupted node headers.

A C-language structural verifier is provided as source code at `/app/tools/pgverify.c`. When compiled and run against a database file, it performs comprehensive B+tree validation — meta-page CRC, key ordering, balanced leaf depth, separator-key consistency with child subtrees, pointer validity, cumulative offset integrity, and full page reachability — exiting 0 if the file is structurally valid and 1 otherwise.

Build an executable tool at `/app/recover` that performs both integrity analysis and structural repair of corrupted database files.

**Usage:** `/app/recover /path/to/input.db /path/to/output.db`

The tool must write a JSON integrity report to stdout and a repaired database file to the specified output path. It must exit with code 0.

**JSON report schema:**

```json
{
  "meta": {
    "magic_valid": true,
    "root_page": 6,
    "num_pages": 7,
    "checksum_valid": true
  },
  "errors": [
    {"type": "sort_violation", "page": 2, "detail": "description"}
  ],
  "recovered_kvs": [
    ["key_string", "value_string"]
  ],
  "stats": {
    "total_pages": 7,
    "reachable_pages": 7,
    "orphaned_pages": 0
  }
}
```

Error type values: `bad_checksum`, `dangling_pointer`, `sort_violation`, `orphaned_pages`, `corrupted_node`.

`recovered_kvs` contains all key-value pairs successfully parsed from reachable, parseable leaf nodes — including leaves with sort violations but excluding nodes with unparseable binary data. Keys and values are UTF-8 strings, sorted lexicographically by key.

`reachable_pages` counts the meta page plus all pages visited during tree traversal (including corrupted nodes that were reached but couldn't be fully parsed). `orphaned_pages` equals `total_pages - reachable_pages`.

**Repaired database requirements:**

The output file must contain exactly the `recovered_kvs` key-value pairs organized in a structurally valid B+tree satisfying all invariants from `/app/FORMAT.md`. The meta page must have correct magic, root pointer, page count matching the file size, and a valid CRC-32 checksum. The file must have no orphaned pages and must pass the compiled `pgverify` verifier with exit code 0.