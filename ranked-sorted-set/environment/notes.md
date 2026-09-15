# Sorted Set Memory Investigation

Date: 2024-03-15
Author: J. Chen (no longer on team)

## Background

Multiple application teams share a Redis deployment. Finance team flagged
unusually high memory usage relative to their data volume. Sorted sets appear
to be the main contributor.

## What I observed

- 25 sorted sets across 5 namespaces: leaderboard, timeline, index, cache, analytics
- Quick spot-check with `MEMORY USAGE timeline:user_1` returned a number that
  seems high for only ~300 entries
- The analytics sets (1000 entries) are large but their per-entry cost looks
  roughly in line with expectations

## What I tried

- Started building a profiler at `/app/tools/profiler.py` to automate the analysis
- Tool connects to Redis and gathers metrics but the overhead calculation might be
  off — the numbers it produces don't match what I'd expect from theory
- Ran into crashes during testing that I didn't have time to debug
- Read a DragonflyDB engineering blog that claims Redis skiplists have ~37 bytes
  per-entry overhead. This is computed from the actual skiplist node struct layout
  and level promotion probability. Want to verify this independently.

## Hypotheses

1. Encoding issue? Redis uses listpack for small sorted sets and skiplist for
   large ones. The transition threshold matters. Need to check with
   `OBJECT ENCODING <key>` for each namespace.
2. Member string length might be inflating memory for some sets.
3. Configuration could be non-default — the deployment was set up by a
   contractor who may have tuned parameters.

## TODO (never completed)

- [ ] Fix profiler crashes and incorrect calculations
- [ ] Check all sorted set encodings and cross-reference with cardinality
- [ ] Verify theoretical skiplist overhead from first principles
- [ ] Identify root cause of excessive memory
- [ ] Produce final audit report with per-set breakdown
