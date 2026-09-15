# Puppet Forge Dependency Resolver

A tool for resolving Puppet module dependencies from a Puppetfile against a local forge database.

## Usage

```
cd /app
python3 -m resolver resolve <Puppetfile>
```

Outputs resolved module versions as JSON to stdout. On success, writes a `Puppetfile.lock` alongside the input file.

## Components

- `resolver/__main__.py` — CLI entry point
- `resolver/parser.py` — Puppetfile parser (forge and git source entries)
- `resolver/constraints.py` — Version constraint engine with Puppet's `~>` operator
- `resolver/solver.py` — Backtracking dependency resolver (highest-version-first)
- `resolver/lockfile.py` — Lockfile writer
- `forge_db/modules.json` — Local forge database mirror

## Puppetfiles

- `Puppetfile` — Production deployment manifest (forge + git sources)
- `Puppetfile.staging` — Staging environment with additional modules
- `Puppetfile.conflict` — Test input with known unsatisfiable requirements
- `Puppetfile.circular` — Test input with circular dependencies

## Reference Documents

- `spec/puppet_versioning.md` — Puppet module version constraint specification
- `schema/resolution.jq` — jq validation script for resolution JSON output
- `schema/explain.jq` — jq validation script for conflict explanation output
- `schema/cycle.jq` — jq validation script for circular dependency error output

## Forge Database Format

```json
{
  "modules": {
    "owner/name": {
      "versions": {
        "X.Y.Z": {
          "dependencies": [
            {"name": "dep_owner/dep_name", "version_requirement": ">= 1.0.0 < 3.0.0"}
          ]
        }
      }
    }
  }
}
```

## Version Constraint Syntax

- Bare version: `9.6.0` — exact pin
- Comparison: `>=`, `<=`, `>`, `<`, `=` followed by version
- Range: `>= 3.0.0 < 5.0.0` (space-separated, all must hold)
- Pessimistic (twiddle-wakka): `~> X.Y` or `~> X.Y.Z` (see `spec/puppet_versioning.md`)

## Puppetfile Format

```ruby
forge 'https://forge.puppet.com'

mod 'owner/name', 'constraint'          # Forge source with version constraint
mod 'owner/name'                        # Forge source, resolve to latest
mod 'owner/name',
  :git => 'https://github.com/...',     # Git source
  :tag => 'v1.0.0'
```

## Resolution Algorithm

The resolver uses backtracking search:
1. Process requirements in order (first requirement first)
2. For each unresolved module, try compatible versions from highest to lowest
3. For each candidate version, collect its transitive dependencies
4. Recursively resolve transitive deps + remaining requirements
5. If resolution fails, backtrack and try the next candidate version
6. If a module is already resolved, verify the existing version satisfies the new constraint
