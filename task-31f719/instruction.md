A Rust workspace at `/app/workspace/` contains a main crate (`hyperkernel`) with a complex Cargo feature graph and five local dependency crates. The feature declarations use modern `dep:` optional dependency syntax alongside legacy implicit feature references, weak (`?/`) conditional dependencies, and per-dependency `default-features` settings. Feature activation propagates transitively through dependency crates' own internal feature graphs.

The Cargo toolchain is installed and the workspace compiles. Analyze the complete feature dependency graph and answer all queries in `/app/queries.json`. Produce `/app/results.json` — a JSON array of `{"id": <int>, "result": <value>}` objects.

## Query Types

- **`resolve`**: Given `features` (list of feature names to enable on `hyperkernel`), compute the complete set of transitively enabled items. An item is: a hyperkernel feature name (including any auto-generated implicit features), an enabled optional dependency name, or an activated dependency feature formatted as `dep_name/feature_name`. When a dependency is enabled and its declaration in `hyperkernel` does not set `default-features = false`, that dependency's own default features are also activated; those default features may transitively enable further sub-features within the dependency. Return a sorted list.

- **`implicit_features`**: Return a sorted list of feature names that Cargo auto-generates for the `hyperkernel` package (features not explicitly declared in its `[features]` section).

- **`reverse_deps`**: Given `feature` (a single item name), find all `hyperkernel` features — including auto-generated implicit features but excluding the target itself — that would transitively enable this item when activated individually. Return a sorted list.

- **`feature_diff`**: Given `features_a` and `features_b`, compute the symmetric difference between `resolve(features_a)` and `resolve(features_b)`. Return `{"only_a": [...], "only_b": [...]}` with sorted lists.

- **`minimal_set`**: Given `required` (list of items that must all appear in the resolved set), find a smallest set of `hyperkernel` features (including auto-generated implicit features as candidates) whose resolution includes every required item. Return a sorted list.