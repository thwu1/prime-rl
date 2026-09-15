# Content Store Reference

The content store is the persistence layer for the KVS Merkle tree. It
stores arbitrary binary blobs indexed by their SHA-1 hash, providing
content-addressable deduplication.

## SQLite Schema

The store is a single SQLite database with one table:

```sql
CREATE TABLE objects (
    hash TEXT PRIMARY KEY NOT NULL,
    size INTEGER NOT NULL,
    object_data BLOB NOT NULL
);
```

- `hash`: SHA-1 blobref (format: `sha1-<40 hex chars>`)
- `size`: byte length of `object_data`
- `object_data`: the raw blob content

## Querying the Store

Use the `sqlite3` CLI to explore:

```bash
# Count all stored objects
sqlite3 /app/content.sqlite "SELECT COUNT(*) FROM objects"

# List all hashes and sizes
sqlite3 /app/content.sqlite "SELECT hash, size FROM objects ORDER BY hash"

# Extract a specific blob (as text if UTF-8)
sqlite3 /app/content.sqlite "SELECT object_data FROM objects WHERE hash='sha1-...'"

# Extract binary blob to file
sqlite3 /app/content.sqlite "SELECT writefile('/tmp/blob.dat', object_data) FROM objects WHERE hash='sha1-...'"
```

For JSON blobs (directory entries), `jq` can be used for inspection:

```bash
sqlite3 /app/content.sqlite "SELECT object_data FROM objects WHERE hash='sha1-...'" | jq .
```

## Integrity Verification

A blob is **valid** if and only if:

    SHA1(object_data) == hash

If this invariant is violated, the blob is **corrupted** — its data cannot
be trusted and any tree entries reachable only through this blob are
considered unreachable.

To verify a specific blob:

```bash
sqlite3 /app/content.sqlite "SELECT hex(object_data) FROM objects WHERE hash='sha1-...'" \
  | xxd -r -p | sha1sum
```

Or in Python:

```python
import hashlib, sqlite3
conn = sqlite3.connect("/app/content.sqlite")
row = conn.execute("SELECT object_data FROM objects WHERE hash=?", (h,)).fetchone()
actual = "sha1-" + hashlib.sha1(row[0]).hexdigest()
valid = (actual == h)
```

## Dangling References

A dirref or valref that references a hash not present in the `objects` table
is a **dangling reference**. The subtree or value it points to is permanently
lost.

## Orphaned Blobs

A blob is **orphaned** if it is not referenced (directly or transitively)
from any namespace root. Orphaned blobs represent data from previous
versions that has not been garbage collected.

## Roots File

The file `/app/roots.json` contains the current root dirref for each
namespace:

```json
{
  "namespaces": {
    "<name>": {
      "root": {"type": "dirref", "data": ["sha1-..."], "ver": 1},
      "sequence": <int>,
      "owner": <uid>
    }
  }
}
```

The `root` field is a dirref treeobj pointing to the namespace's root
directory blob in the content store. The `sequence` is a monotonic
version counter.
