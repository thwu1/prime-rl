The Cargo workspace at `/app/` contains five crates: `signal-core`, `signal-net`, `signal-storage`, `signal-embedded`, and `signal-cli`.

It exhibits contradictory build behavior — full-workspace compilation succeeds, but individual crate builds fail:

- `cargo check --workspace` — succeeds
- `cargo check -p signal-storage` — fails
- `cargo check -p signal-net` — fails
- `cargo test -p signal-net` — fails

Diagnose the root causes of these inconsistencies and redesign the workspace architecture to eliminate them.

## Required outcomes

**Build correctness.** All of the following must succeed after your changes:

```
cargo check --workspace
cargo check -p signal-storage
cargo check -p signal-net
cargo test -p signal-net
```

**Architectural properties.** The fixed workspace must satisfy:

- Feature resolution must isolate dev-dependency and build-dependency features from normal library builds
- Dependencies used by multiple member crates (serde, serde_json, signal-core) are consolidated at the workspace level and inherited by members
- Every crate explicitly declares each `signal-core` feature its non-test code requires

**Diagnostic report.** Write `/app/migration_report.toml` containing an `[analysis]` section with these keys (values determined entirely by your investigation):

| Key | Type |
|---|---|
| `implicit_feature_count` | integer |
| `testfixture_misuse_crate` | string (crate name) |
| `storage_missing_feature` | string (`signal-core` feature) |
| `storage_uses_module` | string (`signal-core` module) |
| `net_leak_section` | string (`Cargo.toml` dependency section) |