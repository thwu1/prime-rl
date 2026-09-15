A Rust workspace at `/app/` contains six crates (`foundation`, `codec`, `buildutil`, `validator`, `transform`, `server`). The workspace was switched to Cargo resolver v2 but the migration was left incomplete — the workspace no longer compiles.

Design and implement a Python migration analysis tool at `/app/migration_analyzer.py` that programmatically identifies all feature-resolution issues caused by the resolver v1-to-v2 transition. The tool must:

- Parse all workspace-level and per-crate `Cargo.toml` files to build a dependency and feature graph
- Detect feature configurations that are invalid or produce different behavior under resolver v2, covering at minimum: dependencies using the `dep:` prefix without being marked `optional`, dev-dependency feature leaks, host/build-dependency feature leaks, missing feature activations, workspace-level dependency feature gaps, and broken feature propagation chains
- Classify each issue into one of these categories: `dep_not_optional`, `dev_dep_leak`, `host_dep_leak`, `missing_feature`, `workspace_feature_gap`, `broken_propagation`
- Output a JSON report to `/app/migration_report.json` with this schema:
  ```json
  {"issues": [{"crate_name": "...", "file": "...", "category": "...", "dependency": "...", "detail": "..."}]}
  ```
- When invoked with `--apply`, patch the workspace `Cargo.toml` files to resolve all identified configuration issues
- Accept `--workspace DIR` to analyze an arbitrary workspace root (default: script directory) and `--output FILE` for custom report path

The tool must perform real analysis of workspace state — re-running it on the already-fixed workspace must report zero issues.

Additionally, `server/build.rs` contains a code-level bug: the `compute_magic` function uses a polynomial rolling hash instead of the FNV-1a 64-bit algorithm used at runtime by `foundation::hash::fnv1a`. This mismatch causes a runtime assertion failure even after all configuration issues are resolved. Fix this directly — it cannot be detected by configuration analysis alone.

After running the analyzer with `--apply` and fixing the build script, the workspace must satisfy: `cargo check --workspace` succeeds, `cargo test --workspace` passes, and `cargo run -p server` exits 0 with correct output including protocol magic verification, envelope round-trips, packet hash, validation mode, and a completion message.