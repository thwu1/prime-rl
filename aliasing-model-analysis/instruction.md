A Rust project at `/app/` contains six `unsafe` functions that perform various raw pointer and reference manipulations. Some of these functions trigger undefined behavior (UB) under Rust's experimental aliasing models as checked by Miri.

Pre-captured Miri diagnostic output from running each function individually under both aliasing models is available at `/app/diagnostics/`:

- `/app/diagnostics/stacked_borrows/` — Miri output under the default Stacked Borrows model
- `/app/diagnostics/tree_borrows/` — Miri output under the Tree Borrows model (`-Zmiri-tree-borrows`)

**Caution:** The nightly toolchain is no longer installed, so you cannot re-run Miri. The diagnostic files were captured hastily and some may be incomplete or mislabeled. See `/app/NOTES.md` for details. Do not blindly trust every diagnostic file — verify against the source code when something seems off.

A function may have UB under one model but not the other, under both, or under neither.

## Deliverables

1. **Classify** each function and write `/app/classification.json`. Keys must be the exact function names (`interleaved_copy`, `activated_overwrite`, `reborrow_invalidation`, `disjoint_raw_ptrs`, `shared_read_after_mut`, `protector_violation`). Values must be one of: `"sb_only"` (UB only under Stacked Borrows), `"tb_only"` (UB only under Tree Borrows), `"both"` (UB under both), or `"neither"` (no UB under either).

2. **Fix** all functions that have UB under either model by modifying `/app/src/lib.rs`. The fixed code must satisfy:
   - `cargo build` succeeds.
   - `cargo test` passes with all six `#[test]` functions and their assertions preserved (output must contain "6 passed").

3. **Structural constraints** on fixes — the root cause of UB must be eliminated, not merely masked:
   - Functions whose UB stems from conflicting `as_ptr()` / `as_mut_ptr()` borrows (`interleaved_copy`, `activated_overwrite`, `shared_read_after_mut`) must not call `.as_ptr()` in their body. Derive all raw pointers from a single `as_mut_ptr()` instead.
   - `reborrow_invalidation` must not read through the `child` pointer (`*child`) after writing through the `parent` pointer (`*parent = ...`), since that is the access pattern that triggers invalidation under both models.
   - `protector_inner` must not accept a `&mut` parameter. The protector conflict is resolved by passing only raw pointers.