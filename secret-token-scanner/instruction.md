A git repository at `/app/repo` was flagged after a credential leak incident. The engineering team claims all secrets have been removed, but a comprehensive audit of the **entire git object store** is required — secrets may persist in historical commits, orphaned objects, or git metadata that standard cleanup procedures miss.

The token format specification is at `/app/token_spec.yaml`, describing three providers (`apx`, `nxs`, `vlt`) with distinct structures and integrity checksums.

Produce `/app/audit.json` — a JSON object with a `findings` array where each entry contains:

- `token` — the full matched token string
- `provider` — provider identifier: `apx`, `nxs`, or `vlt`
- `location_type` — where the token resides in the git object model: `blob`, `tag_annotation`, `note`, or `stash`
- `reachable` — boolean indicating whether the containing git object is reachable from any named ref (branches, tags, notes refs, stash ref); reflog-only references do **not** count as reachable

Only report tokens whose integrity checksums validate. Deduplicate by token value — each unique token string should appear exactly once. Invalid tokens (corrupted checksums) scattered throughout the repository must be excluded.