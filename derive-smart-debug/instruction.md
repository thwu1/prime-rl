A Rust workspace at `/app/` contains two crates:

- `/app/smart_debug/` — a proc-macro crate with a skeleton `#[derive(SmartDebug)]` macro that currently returns an empty token stream
- `/app/smart_debug_tests/` — integration tests exercising the macro

Implement the `SmartDebug` derive macro in `/app/smart_debug/src/lib.rs` so that `cargo test` passes in `/app/`.

The macro generates `std::fmt::Debug` implementations and must support:

- **Structs**: named fields, tuple structs, and unit structs
- **Enums**: unit, tuple, and struct variants
- **`#[debug(skip)]`**: omit the field from debug output entirely
- **`#[debug(fmt = "...")]`**: use the given format string instead of the default `Debug` format for the field value (single `{}` placeholder for the field)
- **`#[debug(rename = "...")]`**: display a different field name in the output
- **`#[debug(with = "path::to::fn")]`**: delegate formatting to a user-provided function with signature `fn(&FieldType, &mut Formatter) -> fmt::Result`
- **`PhantomData<T>` fields**: auto-skip (do not display, do not require `T: Debug`)
- **Smart generic bounds**: only add `T: std::fmt::Debug` where-clause predicates for type parameters `T` that appear in fields which are actually formatted (not skipped, not PhantomData)

Output format must match `std::fmt::Formatter::debug_struct`, `debug_tuple`, and `write_str` conventions.