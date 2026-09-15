# KVS Tree Object Specification

The KVS stores data in a content-addressable Merkle tree. Each node in the
tree is represented as a **treeobj** — a JSON object with `type`, `data`,
and `ver` fields. The `ver` field is always `1` in the current format.

## Blobref Format

All content hashes use SHA-1 in the format:

    sha1-<40 hex digits>

Example: `sha1-4087718d190b373fb490b27873f61552d7f29dbe`

The blobref is computed as `"sha1-" + hex(SHA1(blob_bytes))`.

## Treeobj Types

### val — Inline Value

Stores a small value directly in the treeobj. The `data` field contains the
value encoded as: `base64(json_serialize(value) + NUL_byte)`.

```json
{"type": "val", "data": "ImZjZnMiAA==", "ver": 1}
```

To decode: base64-decode `data`, strip trailing `\x00`, then JSON-parse.

The JSON serialization uses compact format with sorted keys:
`json.dumps(value, sort_keys=True, separators=(',', ':'))`.

### valref — Value Reference

References a large value stored as a raw blob in the content store.
The `data` field is an array of blobrefs (typically one).

```json
{"type": "valref", "data": ["sha1-abc123..."], "ver": 1}
```

The blob content is the raw value bytes (for structured data, this is
typically a JSON document). Multiple blobrefs indicate a value split
across multiple blobs, to be concatenated in order.

### dirref — Directory Reference

References a directory stored as a blob in the content store.
The `data` field is an array containing one blobref.

```json
{"type": "dirref", "data": ["sha1-def456..."], "ver": 1}
```

The referenced blob contains a JSON object mapping child names to their
treeobj entries. The JSON is serialized with sorted keys and compact
separators: `json.dumps(children, sort_keys=True, separators=(',', ':'))`.

Example directory blob content:

```json
{"child_a":{"data":"NDIA","type":"val","ver":1},"child_b":{"data":["sha1-..."],"type":"dirref","ver":1}}
```

### symlink — Symbolic Link

A reference to another key path, resolved at lookup time.

Same-namespace symlink — `data` is a string (dotted key path):

```json
{"type": "symlink", "data": "config.scheduler.queue_config", "ver": 1}
```

Cross-namespace symlink — `data` is an object with `namespace` and `target`:

```json
{"type": "symlink", "data": {"namespace": "jobs", "target": "active"}, "ver": 1}
```

Symlinks are not followed during tree traversal of the content store.
They represent logical references that may or may not resolve depending
on the current state of the target namespace.

## Key Path Convention

Keys in the KVS are hierarchical, using `.` (dot) as the path separator.
A path like `config.scheduler.policy` refers to the `policy` entry inside
the `scheduler` directory inside the `config` directory at the namespace root.

## Namespace Roots

Each namespace has an independent root directory, represented as a dirref
treeobj. The root's blobref serves as the version identifier for that
namespace's state. Different versions of a namespace may share subtree
blobs (structural sharing / deduplication).
