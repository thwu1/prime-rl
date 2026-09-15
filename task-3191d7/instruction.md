A security audit requires a comprehensive secret scanner for the NexAuth credential ecosystem. The token format specification is at `/app/token_spec.json` and the target workspace is at `/app/codebase/`.

NexAuth uses five token types (`nxa`, `nxs`, `nxr`, `nxd`, `nxi`) sharing a common structure: a 3-character prefix, underscore separator, Base62 payload, and 6-character CRC32 checksum encoded in Base62. Each type computes its checksum over different input bytes — study the specification carefully.

Build a scanner that finds every NexAuth token across the entire workspace, validates each token's CRC32 checksum per the specification, and classifies tokens by type and validity. The workspace is a realistic development environment where secrets have been embedded in source code, configuration files, data stores, version control metadata, encrypted vaults, archived backups, and binary data dumps — using a variety of formats, encodings, and tools. Some secrets may only be recoverable through specialized CLI tools or obscure version control features. Be thorough — decoy strings with similar patterns that fail format validation must be rejected.

Write results to `/app/report.json`:

```json
{
  "tokens": [
    {"file": "<where found>", "token": "<full decoded token>", "type": "<type_id>", "valid": true|false}
  ],
  "summary": {
    "total": <int>,
    "valid": <int>,
    "invalid": <int>,
    "by_type": {"nxa": <count>, "nxs": <count>, "nxr": <count>, "nxd": <count>, "nxi": <count>}
  }
}
```

Counts in `summary` must be consistent with the `tokens` list.