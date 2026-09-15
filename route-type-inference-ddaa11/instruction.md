A TypeScript routing library at `/app/` has defective source files. Both compile-time type checking and runtime tests fail.

**Source files (may be modified):**
- `/app/src/types.ts` — Type-level definitions for route path parameter inference
- `/app/src/url.ts` — Runtime path manipulation and pattern-matching utilities
- `/app/src/router.ts` — Pattern-matching HTTP router that depends on `url.ts`

**Read-only files (must not be modified):**
- `/app/src/type-checks.ts` — Compile-time type assertions exercising all type definitions
- `/app/src/__tests__/url.test.ts` — Runtime tests for path utilities
- `/app/src/__tests__/router.test.ts` — Runtime tests for the pattern router
- `/app/package.json`, `/app/tsconfig.json`, `/app/vitest.config.ts`

**Constraints:**
- All exported type names, function signatures, and public class interfaces must be preserved
- The source files are interdependent: `router.ts` imports functions from `url.ts`; `type-checks.ts` imports types from `types.ts`. Failures cascade across module boundaries.

**Success criteria** — both commands must exit 0:
```
cd /app && npm install && npx tsc --noEmit
cd /app && npx vitest run
```
