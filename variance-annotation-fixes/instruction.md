A TypeScript library at `/app/` has type-safety defects across its compiler configuration and generic type definitions. The project contains source modules under `/app/src/` and a `tsconfig.json`.

**Goal:** `tsc --noEmit --project /app/tsconfig.json` must exit with code 0, and all verification tests must pass.

**Requirements:**

1. The compiler configuration must enforce maximum type-checking strictness. No safety-related compiler options may be disabled or weakened.

2. Every exported generic type parameter across all `.ts` source files (excluding `index.ts`) must carry an explicit variance annotation (`in`, `out`, or `in out`) that correctly reflects how the parameter is structurally used within the type body.

3. `/app/src/compose.ts` is a stub that must be implemented. Define and export these generic types:
   - `Source<T>`, `Sink<T>`, `Channel<T>` (single type parameter)
   - `Through<T, U>`, `Pipeline<T, U>`, `Duplex<T, U>` (two type parameters)
   - `Fold<T, R>` (two type parameters)
   - `Splitter<T, A, B>` (three type parameters)

   Each type must have at least two members. The member signatures must establish the variance of every type parameter through structural usage positions. Verification tests check assignability bidirectionally using a class hierarchy.

4. `/app/src/index.ts` must re-export all source modules.

**Constraints:**

- Do not remove or rename existing exported types or their members.
- Do not use `@ts-ignore`, `@ts-expect-error`, type assertions, or `any`.
- Do not relax compiler strictness settings below maximum.
- TypeScript version: `npm install -g typescript@5.4.5`.
