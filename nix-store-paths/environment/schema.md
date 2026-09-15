# Audit Report Schema

The audit report must be written to `/app/audit_report.json`.

## JSON Structure

```json
{
  "audit_results": [
    {
      "filename": "<narinfo filename, e.g. 'abc123.narinfo'>",
      "status": "<one of the status classifications below>",
      "store_path": "<StorePath value from the narinfo file>",
      "computed_path": "<recomputed store path, or null if uncomputable>",
      "content_hash_hex": "<SHA-256 content hash in hexadecimal, or null>",
      "content_hash_nix32": "<SHA-256 content hash in Nix base-32, or null>",
      "content_hash_sri": "<SHA-256 content hash in SRI format, or null>",
      "derivation_type": "<flat, recursive, or text — as claimed by the CA field, or null>",
      "error_detail": "<human-readable error description, or null if valid>"
    }
  ],
  "summary": {
    "total": "<integer: total entries>",
    "valid": "<integer>",
    "path_mismatch": "<integer>",
    "hash_format_error": "<integer>",
    "type_inconsistency": "<integer>",
    "missing_field": "<integer>"
  }
}
```

## Status Classifications

Apply in this priority order:

1. **missing_field** — The CA field is absent from the narinfo file.
2. **hash_format_error** — The CA field is present but the content hash cannot be decoded to raw bytes.
3. **type_inconsistency** — The content hash decodes successfully, but the recomputed store path (using the claimed derivation type) does not match the StorePath. However, recomputing with a *different* derivation type *does* produce a matching path.
4. **path_mismatch** — The content hash is valid, the recomputed path does not match StorePath, and no alternative derivation type produces a match either.
5. **valid** — The recomputed store path matches StorePath exactly.

## Field Rules

- Entries in `audit_results` must be sorted by `filename` in lexicographic order.
- `computed_path` is null when the content hash is undecodable or the CA field is missing.
- All three hash fields (`content_hash_hex`, `content_hash_nix32`, `content_hash_sri`) are present together or all null.
- `error_detail` is null for valid entries; a non-empty string for all others.
- `derivation_type` is null only when the CA field is missing.
