Build a Python dependency resolver at `/app/resolver/` that resolves package dependencies against a local package index at `/app/index/packages.json`.

## Package Index Format

The index file maps lowercase package names to their version metadata:

```json
{
  "package-name": {
    "versions": {
      "1.0.0": {
        "dependencies": ["other-pkg>=1.0,<2.0", "cond-dep>=1.0; sys_platform == 'linux'"],
        "requires_python": ">=3.8",
        "extras": {
          "feature": ["optional-dep>=2.0"]
        }
      }
    }
  }
}
```

Dependencies use PEP 508 syntax. `requires_python` is `null` when unconstrained. Extras map group names to lists of additional dependencies activated when the extra is requested.

## Required Interface

The module at `/app/resolver/` must export:

- `resolve(requirements, index_path, python_version, sys_platform)` — takes a list of PEP 508 requirement strings, the path to the index JSON, a Python version string (e.g. `"3.11"`), and a platform string (e.g. `"linux"` or `"win32"`). Returns a `dict` mapping canonical lowercase package names to resolved version strings.

- `ResolutionError` — exception raised when no valid resolution exists.

## Resolution Semantics

- Support PEP 440 version specifiers: `==`, `!=`, `>=`, `<=`, `>`, `<`, `~=`
- Resolve transitive dependencies recursively
- Activate extra dependency groups when requested via bracket syntax (e.g. `pkg[extra]>=1.0`)
- Evaluate PEP 508 environment markers (`sys_platform`, `python_version`) to conditionally include or exclude dependencies
- Skip package versions whose `requires_python` is incompatible with the given Python version
- Always select the highest compatible version for each package; use backtracking when a choice leads to a downstream conflict
- Raise `ResolutionError` for unsatisfiable constraint sets
- Return version strings matching the format in the index (e.g. `"2.1.0"`)