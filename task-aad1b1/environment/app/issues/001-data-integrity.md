# Issue 001: Non-canonical structure after mixed operations

## Reported by: replication-team
## Severity: High
## Component: store/persistent_map.py

## Description

After switching to the new persistent map backend, our replication layer
is generating spurious change notifications. Two map instances built from
the same logical data sometimes produce different internal structures,
causing `diff()` to report phantom changes.

## Reproduction

1. Build a map by inserting two keys that share the same depth-0 hash
   prefix (e.g., keys `1` and `33` in CPython where `hash(n) == n`).
2. Delete one key so the sub-tree shrinks to a single remaining entry.
3. Build a fresh map containing only that remaining key.
4. Run `diff()` between the two — expected empty, got non-empty.

The root cause seems to be that after deletion the internal tree layout
doesn't match what a fresh insert-only build produces.

## Impact

False-positive change detection in replication causing unnecessary data
syncs and increased network traffic. Downstream consumers receive
spurious update events.
