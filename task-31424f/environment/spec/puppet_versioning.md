# Puppet Module Version Constraint Specification

## Version Format

Puppet modules use semantic versioning: `MAJOR.MINOR.PATCH`

All three components are required for version identifiers in the forge database
(e.g., `9.6.0`). Constraint expressions may use two-part (`X.Y`) or three-part
(`X.Y.Z`) forms depending on the operator.

## Constraint Operators

### Exact Pin

A bare three-part version string pins to that exact version:

- `9.6.0` — matches only version `9.6.0`

### Comparison Operators

- `>= X.Y.Z` — version must be greater than or equal to `X.Y.Z`
- `<= X.Y.Z` — version must be less than or equal to `X.Y.Z`
- `> X.Y.Z` — version must be strictly greater than `X.Y.Z`
- `< X.Y.Z` — version must be strictly less than `X.Y.Z`
- `= X.Y.Z` — version must equal `X.Y.Z` (same as exact pin)

### Range Constraints

Multiple comparison operators may appear space-separated in a single constraint
string. All conditions must hold simultaneously:

- `>= 3.0.0 < 5.0.0` — version must satisfy both `>= 3.0.0` AND `< 5.0.0`

### Pessimistic Operator (`~>` — "twiddle-wakka")

The pessimistic operator constrains the version to the same "significance level"
as the specified version. The number of parts in the version determines which
component is allowed to vary:

- **Two-part form** (`~> X.Y`): Equivalent to `>= X.Y.0, < (X+1).0.0`

  The major version is fixed; any minor and patch versions are allowed.

  - `~> 1.0` matches `1.0.0`, `1.5.3`, `1.99.99` but NOT `2.0.0`
  - `~> 8.1` matches `8.1.0`, `8.99.0` but NOT `9.0.0` or `8.0.0`

- **Three-part form** (`~> X.Y.Z`): Equivalent to `>= X.Y.Z, < X.(Y+1).0`

  The major and minor versions are fixed; only the patch version may vary.

  - `~> 8.6.0` matches `8.6.0`, `8.6.5` but NOT `8.7.0`
  - `~> 1.2.3` matches `1.2.3`, `1.2.99` but NOT `1.3.0`

## Module Name Resolution

Module names in Puppet are **case-insensitive**. The identifiers
`puppetlabs/stdlib` and `Puppetlabs/Stdlib` refer to the same module. Resolvers
MUST perform case-insensitive matching when:

1. Looking up modules in forge databases
2. Checking whether a dependency is already resolved
3. Recording resolved module names (use a canonical lowercase form)

Upstream forge metadata may contain dependency names with inconsistent casing
(e.g., a module may declare a dependency on `Puppetlabs/Stdlib` even though the
canonical forge name is `puppetlabs/stdlib`). The resolver must handle this
transparently.

## Git-Sourced Modules

Modules sourced from git repositories (`:git =>` in the Puppetfile) are NOT
resolved from the Puppet Forge. They must be:

1. Excluded from forge dependency resolution entirely
2. Recorded in the lockfile's `git_modules` section with their name, git URL,
   and ref

## Resolution Semantics

When multiple versions of a module are available:

1. Try the highest version first (prefer newest compatible version)
2. Use backtracking when a chosen version leads to unsatisfiable downstream
   constraints
3. The resolution state — both the set of resolved module versions AND the set
   of attempted version assignments — MUST be properly saved and restored during
   backtracking. Failure to restore the attempted-assignments set causes the
   resolver to permanently skip module versions that were tried in an earlier
   (abandoned) branch of the search tree, even when those versions would be
   valid in the current branch's constraint context.
4. If a module is already resolved (from a prior requirement), verify the
   existing version satisfies the new constraint rather than re-resolving.
