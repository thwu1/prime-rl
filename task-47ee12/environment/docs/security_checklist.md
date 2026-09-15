# Pipeline Configuration Security Checklist

## Token Security
- No placeholder or default token values (e.g., REPLACE-ME, TODO, CHANGEME)
- Each independently-administered lab should have a unique callback token
- Tokens inherited via YAML merge keys should be flagged — shared tokens
  between independently-administered labs is a security concern
- Token descriptions should not leak sensitive information

## Priority Configuration
- All LAVA labs must have valid priority ranges (min <= max)
- Overlapping priority ranges between labs should be identified
- Priority overlaps combined with different tree rules cause scheduling ambiguity

## Tree Rules
- No contradictory include/exclude rules within the same lab (e.g., both
  `android` and `!android` in the same tree rules list)
- Cross-lab conflicts: a tree allowed in one lab but denied in another lab
  at the same priority tier indicates potential misconfiguration

## Storage Backends
- SSH storage entries must have all required fields (host, port, base_url)
- Backend storage entries should have consistent URLs (same environment)
- No mix of staging/production URLs in the same storage entry

## Safety Features
- Queue depth limiting should be enabled unless explicitly justified
- All LAVA labs must have their URL configured
- Callback notification should be configured for all LAVA labs

## YAML Integrity
- Merge key inheritance should not silently override security-critical fields
- All anchor references should resolve correctly
