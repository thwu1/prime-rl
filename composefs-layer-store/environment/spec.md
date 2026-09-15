# Content-Addressed Layer Store Specification

## Overview

`/app/cfs-tool` is a CLI tool that manages a content-addressed filesystem
layer store. The tool separates file content (data) from filesystem structure
(metadata), stores data objects by SHA-256 digest for automatic deduplication,
and supports OCI-inspired layer merge operations with whiteout semantics.

## Object Store Format

Objects are stored in a content-addressed store directory using SHA-256 digests.

- **Object path**: `<store>/objects/<digest[0:2]>/<digest>`
  - The first two hex characters of the digest form a prefix directory for sharding.
- Objects contain raw file content (regular files only).
- Empty files (size 0) are NOT stored as objects in the store.

## Manifest Format (JSON)

A manifest describes a filesystem layer:

```json
{
  "version": 1,
  "entries": [
    {
      "path": "usr/bin/hello",
      "type": "file",
      "size": 42,
      "mode": "0755",
      "sha256": "abcdef1234..."
    },
    {
      "path": "usr/lib",
      "type": "directory",
      "mode": "0755"
    },
    {
      "path": "usr/lib/libfoo.so",
      "type": "symlink",
      "link_target": "libfoo.so.1"
    }
  ],
  "whiteouts": [],
  "opaque": []
}
```

### Top-level fields

| Field       | Type             | Required | Description                                   |
|-------------|------------------|----------|-----------------------------------------------|
| `version`   | integer          | yes      | Must be `1`                                   |
| `entries`    | array of objects | yes      | Filesystem entries, sorted by `path`          |
| `whiteouts`  | array of strings | yes      | Paths to delete from lower layers during merge |
| `opaque`     | array of strings | yes      | Opaque directory paths (see merge semantics)  |

### Entry fields

| Field         | Present for types    | Description                                            |
|--------------|---------------------|--------------------------------------------------------|
| `path`        | all                 | Relative path from layer root, using `/` separators     |
| `type`        | all                 | One of: `file`, `directory`, `symlink`                  |
| `size`        | `file`              | File size in bytes                                      |
| `mode`        | `file`, `directory` | POSIX permission bits as 4-digit octal string (e.g. `"0755"`) |
| `sha256`      | `file` (size > 0)   | SHA-256 hex digest of file content                      |
| `link_target` | `symlink`           | Symlink target path                                     |

### Entry sorting

Entries MUST be sorted by `path` in lexicographic (ASCII) order.

### Whiteout metadata

Whiteout information is stored at the top level of the manifest, separate from entries:

- **`whiteouts`**: A sorted list of paths to delete from lower layers during merge.
  Example: `["usr/lib/libapp.so.1"]` means "remove `usr/lib/libapp.so.1` from the base layer."

- **`opaque`**: A sorted list of directory paths that are opaque. During merge, ALL base entries
  under an opaque directory (including the directory itself) are removed, and only the overlay's
  own entries in that directory survive.
  Example: `["etc"]` means "remove all base entries whose path equals `etc` or starts with `etc/`, then add overlay entries."

  **Important**: opaque matching must be exact — `"etc"` matches `etc` and `etc/config.ini` but
  must NOT match `etc_backup` or `etc_backup/file`. Use `path == dir` or `path.startswith(dir + "/")`.

Both fields MUST be present in every manifest (use empty lists `[]` when there are no whiteouts).

## Commands

### `import`

```
cfs-tool import <source-dir> <store-dir> --manifest <output.json>
```

Scan `<source-dir>` recursively. For each entry:

- **Directories** (excluding the root directory itself): record as type `directory` with `mode`.
- **Symlinks**: record as type `symlink` with `link_target`. Do NOT follow symlinks — check
  for symlinks BEFORE calling `stat()` to avoid following the link.
- **Regular files**: record as type `file` with `size` and `mode`. If size > 0, store content in
  the object store and record `sha256`. If the object already exists (same digest), skip writing.

**Whiteout sidecar**: If the source directory contains a file named `.whiteouts.json`, parse it:
```json
{
  "remove": ["path/to/delete1", "path/to/delete2"],
  "opaque": ["dir/to/make/opaque"]
}
```
- `remove` entries become the manifest's `whiteouts` list.
- `opaque` entries become the manifest's `opaque` list.
- The `.whiteouts.json` file itself is NOT included in manifest entries.
- If no `.whiteouts.json` exists, both lists default to empty `[]`.

Paths in entries are relative to `<source-dir>`, using `/` as separator.
Mode is POSIX permission bits as a 4-digit zero-padded octal string (e.g. `"0755"`, `"0644"`).

### `checkout`

```
cfs-tool checkout <manifest.json> <store-dir> <output-dir>
```

Reconstruct the directory tree from the manifest's entries:

- Create directories with correct modes.
- Create regular files with correct content (from object store) and modes.
- Create symlinks with correct targets.
- `whiteouts` and `opaque` fields are layer metadata and are IGNORED during checkout.
- Exit 0 on success, non-zero on error.

### `verify`

```
cfs-tool verify <manifest.json> <store-dir>
```

Verify integrity of all objects referenced by the manifest's entries:

- For each `file` entry with `sha256`: check that the object exists at the correct path in the
  store and that its SHA-256 digest matches.
- Print `OK` and exit 0 if all checks pass.
- Print `FAILED: <path> <reason>` for each failure and exit 1 if any check fails.

### `diff`

```
cfs-tool diff <old-manifest.json> <new-manifest.json>
```

Compute differences between two manifests' entries. Output JSON to stdout:

```json
{
  "added": ["path1", "path2"],
  "removed": ["path3"],
  "modified": ["path4"]
}
```

- `added`: paths present in new manifest but absent from old.
- `removed`: paths present in old manifest but absent from new.
- `modified`: paths present in both but differing in any attribute: `type`, `sha256`, `mode`,
  `size`, or `link_target`. Must compare entry attributes, not just path presence.
- Each list sorted lexicographically.

### `merge`

```
cfs-tool merge <base-manifest.json> <overlay-manifest.json> --output <merged.json>
```

Apply overlay layer on top of base layer, resolving whiteout semantics:

1. Start with all base entries.
2. Process **opaque** directories from overlay: for each path D in `overlay.opaque`, remove ALL
   base entries whose path equals D or starts with `D/`. Must NOT match paths that merely share
   a prefix (e.g. opaque `"etc"` must not affect `"etc_backup"`).
3. Process **whiteouts** from overlay: for each path P in `overlay.whiteouts`, remove the base
   entry at path P.
4. Add/override with all overlay entries. Whiteouts apply only to base entries — overlay entries
   at whiteout paths must survive (the overlay both removes the old version and provides a new one).
5. The merged manifest's `whiteouts` and `opaque` lists are set to empty `[]` (whiteouts are
   consumed by the merge and NOT propagated).
6. Sort merged entries by path.
7. Write merged manifest to `<merged.json>`.

### `stats`

```
cfs-tool stats <store-dir>
```

Print JSON to stdout:

```json
{
  "total_objects": 42,
  "total_size_bytes": 123456
}
```

- `total_objects`: number of object files in the store.
- `total_size_bytes`: sum of all object file sizes in bytes.

### `gc`

```
cfs-tool gc <store-dir> <manifests-dir>
```

Garbage-collect unreferenced objects from the store.

1. Scan all `.json` files in `<manifests-dir>`.
2. For each manifest, collect all `sha256` digests from `file` entries.
3. Walk the object store. Remove any object whose digest is NOT in the referenced set.
4. Clean up empty prefix directories.

Print JSON to stdout:

```json
{
  "removed_objects": 3,
  "freed_bytes": 12288,
  "remaining_objects": 8
}
```

- `removed_objects`: number of objects deleted.
- `freed_bytes`: total bytes freed.
- `remaining_objects`: number of objects still in the store.

Exit 0 on success.

### `fsck`

```
cfs-tool fsck <store-dir> <manifests-dir>
```

Comprehensive integrity check of all manifests and objects.

Checks performed:
1. **Schema validation**: Each `.json` manifest must have `version == 1`, `entries` (list),
   `whiteouts` (list), `opaque` (list). Each entry must have `path` and `type`.
   File entries with `size > 0` must have `sha256`.
2. **Sort order**: Manifest entries must be sorted by `path`.
3. **Duplicate paths**: No duplicate `path` values within a single manifest.
4. **Hash verification**: For each file entry with `sha256`, the object must exist in the store
   at `<store>/objects/<digest[0:2]>/<digest>` and its SHA-256 hash must match.
5. **Orphan detection**: Count objects in the store not referenced by any manifest.

Print JSON to stdout:

```json
{
  "status": "clean",
  "manifests_checked": 3,
  "objects_checked": 15,
  "orphaned_objects": 0,
  "errors": []
}
```

- `status`: `"clean"` if no errors, `"dirty"` if any errors found.
- `manifests_checked`: number of manifest files processed.
- `objects_checked`: number of unique objects whose hashes were verified.
- `orphaned_objects`: count of objects in the store not referenced by any manifest.
  Orphans are informational and do NOT affect `status`.
- `errors`: list of error objects, each with:
  - `manifest`: filename of the manifest containing the error.
  - `type`: one of `"missing_object"`, `"hash_mismatch"`, `"schema_violation"`,
    `"sort_violation"`, `"duplicate_path"`.
  - `detail`: human-readable description.

Exit 0 if status is `"clean"`, exit 1 if `"dirty"`.

## store-audit.sh

```
store-audit.sh <store-dir> <manifests-dir>
```

An independent store validation tool implemented as a POSIX shell script (no Python).
Must use `jq`, `find`, and `sha256sum` to validate the store.

Steps:
1. Use `find` to enumerate all object files in `<store-dir>/objects/`.
2. Use `jq` to extract all `sha256` digests referenced by `.json` manifests in `<manifests-dir>`.
3. Use `sha256sum` to verify the integrity of each referenced object.
4. Compute orphan count (objects in store but not referenced by any manifest).

Print JSON to stdout:

```json
{
  "total_objects": 15,
  "referenced_objects": 12,
  "orphaned_objects": 3,
  "integrity_errors": 0,
  "status": "ok"
}
```

- `total_objects`: total object files in the store.
- `referenced_objects`: unique digests referenced by manifests.
- `orphaned_objects`: objects in the store not referenced by any manifest.
- `integrity_errors`: count of objects that fail hash verification or are missing.
- `status`: `"ok"` if `integrity_errors == 0`, `"errors_found"` otherwise.

Exit 0 when status is `"ok"`. Exit 1 when status is `"errors_found"`.
