A Python property-based testing library at `/app/pbt/` is a port of the Rust `quickcheck` crate. The core generator (`/app/pbt/gen.py`) is correct, but `/app/pbt/shrink.py` and `/app/pbt/engine.py` produce incorrect results compared to the Rust reference. The Rust source is at `/app/quickcheck-src/` and a compilable reference binary at `/app/qc-ref/qc_ref.rs` (`rustc /app/qc-ref/qc_ref.rs -o /app/qc-ref/qc-ref`).

## Part 1 -- Debug the PBT Library and Apply It

Fix `/app/pbt/shrink.py` and `/app/pbt/engine.py` so the Python library produces the same outputs as the Rust reference for all inputs.

Three functions in `/app/targets.py` violate their documented contracts. Identify inputs that demonstrate each bug and write the minimal failing inputs to `/app/counterexamples.json`:
```json
{"safe_divide": [a, b], "rle_encode": [...], "unique_sorted": [...]}
```
Then fix the bugs in `/app/targets.py` so all three functions satisfy their documented properties.

## Part 2 -- Implement a Structured Shrinker

Implement `shrink_interval_set(intervals)` in `/app/pbt/structured.py` according to the specification in its docstring.

## Part 3 -- Classify Property Specifications

`/app/merge.py` provides two implementations of interval merging (`merge_intervals_v1` is correct, `merge_intervals_v2` is buggy) along with four candidate PBT properties. Classify each property according to the definitions at the top of `/app/merge.py` and write results to `/app/property_audit_results.json`:
```json
{"prop_idempotent": "<class>", "prop_covers_all": "<class>", "prop_no_growth": "<class>", "prop_each_preserved": "<class>"}
```
where `<class>` is one of `"sound"`, `"weak"`, or `"strong"`.