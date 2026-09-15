The `/app/lib/sigil.js` file implements a UMD reactive signal library. The `/app/plugins/sigil-persist.js` file extends it at runtime by patching additional methods onto the library's prototype.

No TypeScript declaration files exist for either module. Consumer code under `/app/src/` imports and exercises both modules with precise type annotations and `@ts-expect-error` directives that enforce strict type-safety constraints.

Create exactly two files:

- `/app/lib/sigil.d.ts` — declarations for the main library
- `/app/plugins/sigil-persist.d.ts` — declarations for the plugin, integrated with the main library's type system

Success criterion: `cd /app && npm install && npx tsc --noEmit` exits with code 0.

Constraints:

- Only the two declaration files listed above may be created. All other files under `/app/` must remain unchanged.
- Every `@ts-expect-error` directive in the consumer files must trigger exactly one type error. Overly permissive declarations will cause "unused `@ts-expect-error`" compilation failures.
- Examine the JavaScript source files for the runtime API surface and the TypeScript consumer files for the full set of type constraints your declarations must satisfy.
- The TypeScript configuration at `/app/tsconfig.json` and all consumer/source files are integrity-checked and must not be modified.
