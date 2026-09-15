A Rust project at `/app/` contains six example binaries in `/app/examples/`, each implementing an unsafe function with a different pointer aliasing pattern. Analyze each function under both the **Stacked Borrows** (Miri default) and **Tree Borrows** aliasing models, classify whether each has Undefined Behavior under each model, and provide fixed versions of all unsound functions.

Miri is available on the project's nightly toolchain. Stacked Borrows is Miri's default aliasing model. Tree Borrows can be activated via the `MIRIFLAGS` environment variable with `-Zmiri-tree-borrows`. Ensure your testing methodology correctly isolates each aliasing model before recording classifications — verify that Stacked Borrows and Tree Borrows are being tested independently.

The six functions to analyze are: `retag_two_phase`, `write_then_ref`, `local_addr_of`, `double_unique`, `raw_after_reborrow`, `sound_mutation`.

## Deliverables

### `/app/classification.json`

JSON object classifying each function. Keys are the function names listed above. Values are objects with `"stacked_borrows"` and `"tree_borrows"` fields, each set to `"ub"` or `"ok"`.

### `/app/src/fixed.rs`

For every function that has UB under at least one model, provide a fixed version named `<original>_fixed` that passes Miri under **both** Stacked Borrows and Tree Borrows while preserving the intended semantics. The file must contain standalone `fn` definitions with no module wrapper or external crate dependencies. Required signatures and expected return values:

- `fn retag_two_phase_fixed() -> [i32; 2]` — copy `arr[0]` to `arr[1]` starting from `[10, 20]` → `[10, 10]`
- `fn write_then_ref_fixed() -> [i32; 2]` — zero `arr[1]` then copy `arr[0]` over it, starting from `[10, 20]` → `[10, 10]`
- `fn local_addr_of_fixed() -> i32` — store 42 via raw pointer to local, read back → `42`
- `fn double_unique_fixed() -> i32` — write 1 then 2 to same location via raw pointer, read back → `2`
- `fn raw_after_reborrow_fixed() -> i32` — write 42 via raw pointer, read back → `42`