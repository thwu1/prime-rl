# Package Dependency Ratchets

This codebase uses a package-based modularity system inspired by Sorbet packages.
Each package declares which other packages it imports and its `strict_dependencies`
enforcement level.

## Layers

Packages are assigned to one of five architectural layers (see `layers.yml`).
Lower-indexed layers are more foundational; higher-indexed layers are closer
to the user-facing surface. The layering rule is: a package must not depend on
packages in layers above its own.

## Ratchet Levels

The `strict_dependencies` field in each `package.rb` controls enforcement.
Levels are ordered from weakest to strongest:

### `false`
No enforcement. The package can import anything regardless of layer or cycles.
No violations are reported.

### `layered`
The package may only import packages from its own layer or lower layers.
Importing from a higher layer is a violation.

### `layered_dag`
All constraints of `layered`, plus: the package must not participate in any
dependency cycle among packages within its same layer. The cycle check considers
all intra-layer dependency edges (between all packages in that layer) regardless
of other packages' individual enforcement levels.

### `dag`
The package must not participate in any dependency cycle in the full dependency
graph. The cycle check considers all dependency edges between all packages
regardless of other packages' individual enforcement levels.

## Package Manifest Format

Each `package.rb` under `packages/<name>/` declares:
- `layer '<name>'` — the architectural layer
- `strict_dependencies '<level>'` — the enforcement level
- `import <ClassName>` — each imported package (CamelCase class name
  corresponding to the snake_case directory name, e.g. `import PaymentGateway`
  corresponds to `packages/payment_gateway/`)
