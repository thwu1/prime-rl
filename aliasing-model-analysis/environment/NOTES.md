## Diagnostic Capture Notes

These Miri diagnostic files were captured by running each of the six test
functions individually under both aliasing models (Stacked Borrows and Tree
Borrows). The nightly toolchain has since been removed from this system.

**Warning:** Some capture sessions were interrupted or mixed up between
terminal tabs. If a diagnostic file seems inconsistent with the code, verify
the test name printed in the output against the filename — there may be
mismatches. A few files may also be truncated if the terminal was closed
before Miri finished.

## Developer Observations

- `disjoint_raw_ptrs` — appears clean; all pointers derived from single base,
  disjoint offsets.
- `activated_overwrite` — passes `cargo test` normally. The read via `as_ptr()`
  between writes through `as_mut_ptr()` should be fine since Tree Borrows is
  generally more permissive about read-only reborrows than Stacked Borrows.
  Probably OK under both models.
- `protector_violation` — definitely problematic; the protected `&mut` reference
  conflicts with the aliasing raw pointer write.
- `reborrow_invalidation` — the parent write probably invalidates the child tag,
  but this might only be an issue under Stacked Borrows since Tree Borrows has
  more granular per-node state transitions.
