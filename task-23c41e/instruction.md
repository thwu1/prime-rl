A multi-crate Rust workspace at `/app/workspace/` models a unikernel's build system. The root crate `aurora-kernel` has 30+ Cargo features with cross-crate feature propagation through conditional forwarding (`crate?/feat`), optional dependency activation (`dep:crate`), and deprecated aliases. Four sub-crates (`netstack`, `virtio-hal`, `fuse-abi`, `mem-barrier`) serve as optional dependencies and have their own internal feature dependency chains that affect the resolved feature set when features are forwarded from the root crate.

Rust and Cargo are installed. The workspace is pre-resolved (`Cargo.lock` exists). Tools like `cargo metadata`, `cargo tree`, and `jq` are available.

Produce `/app/audit.json` containing four sections:

**`cross_crate_closures`**: For each query in `/app/queries.json` (with `id`, `features`, and `no_default_features`), compute full cross-crate feature resolution as an object keyed by query id. Each result contains:
- `root_features`: sorted list of all activated features on `aurora-kernel` (including transitive activations and the `default` feature itself when defaults are used)
- `resolved_deps`: object mapping each enabled optional dependency name to a sorted list of ALL features activated on it — including features activated transitively within the sub-crate's own feature graph. Include deps enabled with no forwarded features as empty lists. Omit deps that are not enabled at all.

**`minimum_activators`**: For each target in `/app/targets.json` (with `id`, `dep`, `feature`), find the lexicographically smallest single `aurora-kernel` feature that, when enabled alone with `no_default_features=true`, causes the specified feature to be activated on the specified dependency crate. Report `null` if no single feature suffices. Result is an object keyed by target id.

**`conditional_analysis`**: A list of objects, one per conditional forwarding expression (`crate?/feat`) in `aurora-kernel`'s features, sorted by `(parent_feature, expression)`. Each object contains:
- `expression`: the conditional string (e.g. `"virtio-hal?/pci-transport"`)
- `parent_feature`: the feature containing this conditional
- `always_fires`: `true` if enabling the parent feature alone (`no_default_features=true`, no other features) always enables the target dependency — making the conditional always fire when the parent is active
- `trigger_features`: sorted list of all `aurora-kernel` features that, individually with `no_default_features=true`, enable the target dependency

**`dominance_pairs`**: Among features that are not internal (`net`, `virtio`), not deprecated (`console`, `fs`, `fuse`, `mmap`, `trace`, `vsock`), and not `default`: list all ordered pairs `[A, B]` where enabling A alone (`no_default_features=true`) results in B also appearing in the resolved root feature set. Sort the list lexicographically.