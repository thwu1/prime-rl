A Flux-style hierarchical key-value store persists distributed cluster state as a content-addressable Merkle tree in a SQLite database. Three namespaces (`primary` for cluster configuration, `jobs` for job metadata, `checkpoint` for consistency snapshots) are stored using SHA-1 blobrefs with RFC 11-style tree objects (val, valref, dirref, symlink types). The content store has sustained partial corruption: some blob data no longer matches its stored hash, and at least one reference points to a blob that no longer exists.

## Data Sources

- `/app/content.sqlite` — Content-addressable blob store with `objects` table (hash, size, object_data).
- `/app/roots.json` — Namespace root references (dirref treeobjs).
- `/app/docs/treeobj_spec.md` — Tree object format specification.
- `/app/docs/content_store.md` — Content store schema and operations reference.

## Objective

Reconstruct the full KVS state by traversing the Merkle tree from each namespace root. Verify every blob's integrity, resolve symbolic links (including cross-namespace), detect corruption and orphaned data, and write a recovery manifest to `/app/output/manifest.json`.

## Output Schema (`/app/output/manifest.json`)

```json
{
  "namespaces": {
    "<name>": {
      "root_hash": "<sha1-blobref>",
      "resolved_values": {"<dotted.key.path>": "<decoded JSON value>"},
      "symlinks": {
        "<dotted.key.path>": {
          "target": "<target path>",
          "target_namespace": "<namespace name or null>",
          "resolves": true | false
        }
      }
    }
  },
  "integrity": {
    "total_blobs": "<count of rows in objects table>",
    "corrupted_blobs": [{"stored_hash": "<sha1>", "computed_hash": "<sha1>"}],
    "dangling_refs": ["<sha1 not in store>"],
    "unreachable_keys": ["<namespace>::<dotted.path>"]
  },
  "orphaned_blob_count": "<count of blobs not referenced from any root>"
}
```

## Integrity Rules

- **Strict verification**: if `SHA1(blob_data) != stored_hash`, the blob is corrupted. Do not parse or trust its contents. All keys reachable only through a corrupted blob are unreachable.
- **Dangling references**: a dirref/valref whose hash is absent from the store. The subtree is lost; report the parent key as unreachable.
- **Symlink resolution**: a symlink resolves if its target path is reachable in the target namespace (or current namespace for same-namespace symlinks). Symlinks whose targets are unreachable due to corruption should have `resolves: false`.
- **Orphaned blobs**: blobs present in the store but not referenced (directly or transitively) from any namespace root.
- **Unreachable keys**: report the highest-level key path that became inaccessible due to a corrupted or dangling blob (e.g., if a directory's dirref blob is corrupted, report the directory path, not individual children).