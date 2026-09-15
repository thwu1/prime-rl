A git repository at `/app/repo/` represents a project with a history of secret token leaks scattered across its development timeline. Token format specifications for three providers are defined in `/app/providers.yaml` — each uses a different checksum algorithm. One provider requires HKDF-SHA256 key derivation from the hex-encoded master secret at `/app/vault/master.key` before its HMAC-based checksum can be validated. A credential rotation log is at `/app/rotation_log.csv`.

Perform a comprehensive forensic audit that discovers every token ever present in the repository across its **full git object graph** — including history reachable from all branches, tags, and stash entries, as well as dangling/unreachable commits that persist in the object store after branch deletions and commit amendments. Validate each discovered token's integrity checksum per its provider's specification, cross-reference with the rotation log, and classify the security risk.

Write the audit report to `/app/audit_report.json` as a JSON array sorted by `risk_level` priority (critical first, then high, medium, low), then by `first_seen_date` ascending within each level. Each element:

```json
{
  "token_id": "<SHA-256 hex digest of the full token string>",
  "provider": "<provider name from providers.yaml>",
  "token_redacted": "<prefix><asterisks replacing body><checksum>",
  "checksum_valid": true,
  "first_seen_commit": "<full 40-char commit hash where token first appears>",
  "first_seen_date": "<ISO 8601 author date of that commit>",
  "present_at_head": false,
  "rotated": false,
  "risk_level": "high"
}
```

Risk classification:
- **low**: invalid checksum (corrupted or fabricated token)
- **critical**: valid checksum, present in HEAD's working tree, not rotated
- **high**: valid checksum, not in HEAD's tree but reachable from any named ref (branch/tag/stash), not rotated
- **medium**: valid checksum and rotated (regardless of reachability); or valid checksum, only discoverable via dangling/unreachable objects, and not rotated

Report unique tokens only — deduplicate by `token_id`, recording the earliest `first_seen_commit` by author date.