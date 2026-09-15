Two versions of a Rust crate's public API have been captured as rustdoc JSON files:

- `/app/baseline.json` — the baseline (previous) version
- `/app/current.json` — the current (updated) version

These use the unstable `rustdoc-json` output format. Write a program that reads both files, compares the public API surface, and identifies all semantic versioning violations. Produce `/app/report.json` with results.

Your detector must identify these semver-major violation categories:

| Category | Meaning |
|---|---|
| `function_missing` | A public function no longer exists at its prior path |
| `function_parameter_count_changed` | A public function's parameter count changed |
| `constructible_struct_adds_field` | A field was added to a public, externally-constructible struct (not `#[non_exhaustive]`, no private fields) |
| `struct_pub_field_missing` | A public field was removed from a public struct |
| `repr_c_removed` | `#[repr(C)]` was removed from a public type |
| `enum_variant_missing` | A variant was removed from a public enum |
| `trait_method_added` | A required method (no default body) was added to a public trait |
| `pub_module_level_const_missing` | A public module-level constant was removed |

The detector must avoid false positives: field additions to `#[non_exhaustive]` structs, field additions to structs with private fields (not externally constructible), and variant additions to `#[non_exhaustive]` enums are NOT semver violations.

Output format for `/app/report.json`:

```json
{
  "violations": [
    {"type": "<category>", "path": "<crate_name>::<item_name>"},
    ...
  ]
}
```

Paths use `::` as separator (e.g. `semver_testbed::compute`). The rustdoc JSON format is not formally documented — examine the files to determine their schema.