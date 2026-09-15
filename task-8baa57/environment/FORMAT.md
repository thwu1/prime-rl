# Package Registry and Manifest Format

## Registry (`registry.json`)

The registry contains all available packages and their versions:

```json
{
  "packages": {
    "package-name": {
      "1.2.0": {
        "dependencies": {
          "other-package": "^1.0.0"
        }
      }
    }
  }
}
```

Versions follow semantic versioning: `MAJOR.MINOR.PATCH` (all integers).

## Manifest

A manifest declares the root package and its direct dependencies:

```json
{
  "name": "my-app",
  "dependencies": {
    "package-name": "^1.0.0"
  }
}
```

## Version Constraint Syntax

Three constraint forms are supported:

### Caret (`^X.Y.Z`)
Compatible with version. Allows changes that do not modify the left-most non-zero digit.

- `^1.2.3` matches `>=1.2.3` and `<2.0.0`
- `^0.2.3` matches `>=0.2.3` and `<0.3.0`
- `^0.0.3` matches `>=0.0.3` and `<0.0.4`

### Tilde (`~X.Y.Z`)
Approximately equivalent to version. Allows patch-level changes.

- `~1.2.3` matches `>=1.2.3` and `<1.3.0`
- `~2.0.0` matches `>=2.0.0` and `<2.1.0`

### Range (`>=X.Y.Z <A.B.C`)
Explicit inclusive-lower exclusive-upper range.

- `>=1.0.0 <3.0.0` matches any version from `1.0.0` up to (but not including) `3.0.0`

## DIMACS CNF Format

The standard DIMACS format for SAT solver input/output:

```
c comment lines start with 'c'
c var 1 package-name@version
c var 2 other-package@version
p cnf <num_variables> <num_clauses>
1 2 0
-1 -2 0
```

- Comment lines (`c`) map variable numbers to `package@version` identifiers
- Problem line: `p cnf <num_vars> <num_clauses>`
- Each clause is a line of space-separated integer literals ending with `0`
- Positive literal `N` means variable N is true (version selected)
- Negative literal `-N` means variable N is false (version not selected)
