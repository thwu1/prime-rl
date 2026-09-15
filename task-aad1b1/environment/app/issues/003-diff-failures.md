# Issue 003: Change detection (diff) returns incorrect results

## Reported by: data-pipeline-team
## Severity: Critical
## Component: store/persistent_map.py

## Description

The `diff()` operation between map versions produces wrong results in
several scenarios. This breaks our incremental sync pipeline, which
relies on accurate diff output.

### Sub-issue 3a: Self-diff performance regression

Comparing a large map to itself takes O(n) time instead of O(1). The
implementation should detect that two subtree references point to the
same object in memory and skip the traversal entirely. Without this,
self-diff on a 5000-entry map takes measurable time instead of being
instantaneous.

Run `make bench` to see timing in the "Diff identity shortcut" check.

### Sub-issue 3b: Hash-collision value changes not detected

When two keys share the same full 30-bit hash prefix and reside in a
collision bucket, changing the *value* associated with one key is not
reported by `diff()`. The collision-bucket diff appears to check only
key presence, not value equality.

### Sub-issue 3c: Asymmetric tree structure diff is incorrect

When one map has an inline data entry at a trie position and another map
has a sub-node at the same position (e.g., map A has `{0: 'a'}` while
map B has `{0: 'a', 32: 'b'}`, causing a sub-node at the shared depth-0
slot), the diff incorrectly reports all keys as changed — even keys that
exist in both maps with identical values.

## Expected behavior

- `m.diff(m)` returns an empty set in constant time
- Value changes within collision buckets are detected
- Diff correctly handles structural asymmetry between inline entries
  and sub-nodes, reporting only genuinely differing keys
