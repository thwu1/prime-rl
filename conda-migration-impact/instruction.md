Twenty-one conda-forge v1 feedstock recipe directories are in `/app/feedstock/`. A global pinning configuration is at `/app/conda_build_config.yaml`. Recipes use `${{ }}` Jinja-style template expressions with `context:` variable blocks, `pin_subpackage()`, `pin_compatible()`, and `compiler()` functions. Some feedstocks produce multiple outputs.

Perform a comprehensive health audit of this package ecosystem and write the results to `/app/output/audit.json` containing:

- **`packages`**: Sorted array of every distinct package name produced across all feedstocks.

- **`dependency_graph`**: Object mapping each package to a sorted array of its host-requirement package names. Only include dependencies defined within this feedstock set. Exclude compilers and build tools (cmake, ninja, make, pkg-config, autoconf, automake, libtool, nasm, cython, pythran, perl). Resolve template expressions to extract actual package names from `pin_subpackage()` and `pin_compatible()` calls.

- **`run_exports_analysis`**: Object mapping each package that declares valid `run_exports` to `{"max_pin": "<pin_pattern>", "constraint": "<generated_constraint>"}`. The constraint follows conda pin semantics: given a package version `a.b.c` and `max_pin='x.x'`, the generated constraint is `>=a.b.c,<a.(b+1).0a0`. For `max_pin='x'`, it is `>=a.b.c,<(a+1).0a0`. For `max_pin='x.x.x'`, it is `>=a.b.c,<a.b.(c+1).0a0`. Omit packages whose `run_exports` contain unresolvable template references.

- **`build_order`**: Array of all packages in a valid topological build order respecting host dependencies.

- **`migration_detected`**: Compare each package's recipe version against the global pinning configuration (note: global pin keys use underscores where package names use hyphens). A version matches its pin when the version's leading dot-separated components equal the pin's components. Report any mismatch as: `primary_package` (the mismatched package), `recipe_version`, `pinned_version`, and `all_migrated_outputs` (sorted array of all outputs from that feedstock, since co-outputs share a version).

- **`directly_affected`**: Sorted array of non-migrated packages that list any migrated output as a host dependency.

- **`transitively_affected`**: Sorted array of non-migrated, non-directly-affected packages reachable through host dependency chains from affected packages.

- **`rebuild_order`**: All directly and transitively affected packages in a valid topological rebuild order respecting inter-package host dependencies.

- **`pin_conflicts`**: Array of objects for each explicit version constraint on a migrated output found in any affected package's host requirements. Each object: `package`, `dependency`, `constraint` (the version spec string), `new_version`, `satisfiable` (boolean — whether the new recipe version satisfies the constraint using PEP 440 ordering, where alpha versions sort before their release: `1.14.4a0 < 1.14.4`).

- **`recipe_diagnostics`**: Array of objects for detected recipe defects — broken template variable references, invalid `pin_subpackage`/`pin_compatible` targets that reference undefined context variables, or other structural issues. Each object: `feedstock` (directory name), `issue` (short identifier), `detail` (description including the problematic reference).