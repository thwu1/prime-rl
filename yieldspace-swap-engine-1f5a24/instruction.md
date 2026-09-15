A TypeScript project at `/app/` must be completed to implement a fixed-point AMM swap engine using `bigint` arithmetic. The project contains:

- `/app/src/math64x64.ts` -- signed 64.64 fixed-point primitives (provided)
- `/app/src/exp64x64.ts` -- stubs for unsigned 128-bit exponentiation (3 functions to complete)
- `/app/src/yieldmath.ts` -- stubs for AMM swap, boundary, and invariant functions (8 functions to complete)
- `/app/src/verify.ts` -- verification runner (do not modify)

Complete all stub functions. The provided codebase may contain defects in non-stub code that produce incorrect results; diagnosing and correcting any such issues is part of the task.

Validation command: `cd /app && npm install && npx tsx src/verify.ts`

The verifier outputs JSON checked by the test suite against:

- Golden values for four directional swap functions (20 reference outputs total)
- Two mirror round-trips (swap then inverse swap recovers input within tolerance)
- Maturity convergence (at zero time-to-maturity with unit fee, output equals share-price-scaled input)
- Three boundary functions (maximum feasible trade sizes)
- Pool invariant per LP token
- Exponentiation identity property

Function signatures, parameter types, and mathematical specifications are documented in the stub files and existing module code. Do not alter public exports or the verification runner.
