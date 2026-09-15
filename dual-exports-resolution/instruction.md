The `/app/lib/` directory contains `@mathkit/linalg`, a TypeScript ESM library package (`"type": "module"`) providing linear algebra utilities: `Vector` and `Matrix` classes, type definitions (`VectorLike` interface, `Dimension` enum, `fromLike` factory), plugin modules under `plugins/`, and platform-specific code via `#platform` subpath imports. The `/app/consumer/` directory contains a Node.js ESM application that imports from the library through multiple export subpaths.

A symlink at `/app/node_modules/@mathkit/linalg` points to `/app/lib/`.

The project has defects that prevent compilation and execution. Fix all issues so that:

1. `tsc -p /app/lib/tsconfig.json` succeeds with zero errors, producing JavaScript and declaration files under `/app/lib/dist/`.

2. `tsc -p /app/consumer/tsconfig.json` succeeds with zero errors. The consumer's `tsconfig.json` must use `"module": "nodenext"` and `"moduleResolution": "nodenext"`.

3. `node /app/consumer/dist/main.js` executes without errors and prints exactly:
```
cross: [0.00, 0.00, 1.00]
det: -2
trace: 5
dim: 3
from-interface: [1.00, 2.00, 3.00]
rotated: [0.00, 1.00]
lerp: [5.00, 5.00]
mean: [3.00, 4.00]
cov-trace: 8
platform: node-optimized
```

Constraints:

- The library's `"exports"` field must expose subpaths `.`, `./vector`, `./matrix`, `./types`, and `./plugins/*`. All export target paths must reference files produced by `tsc`.
- The library's `"imports"` field targets must resolve at both TypeScript compile time and Node.js runtime.
- Import specifiers in all `.ts` source files must comply with `--moduleResolution nodenext` ESM resolution rules.
- The library compiles with `isolatedModules: true`. Type-only re-exports require appropriate syntax.
- The library uses a self-referencing import via its own package name in `src/index.ts`.
- Any new plugin modules must follow the existing plugin conventions under `src/plugins/`.

Install TypeScript before building: `npm install -g typescript@5.7.3`
