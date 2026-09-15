The file `/app/src/engine.ts` implements a GraphQL value completion engine per the GraphQL Specification (October 2021), Section 6.4.3. It processes a type descriptor tree and a resolved value tree to produce a spec-compliant `{ data, errors }` response.

The implementation has defects in several interacting subsystems. Fix `/app/src/engine.ts` so that all tests pass when run via `cd /app && npx tsx src/cli.ts`.

The engine's CLI (`/app/src/cli.ts`) reads JSON from stdin with shape `{ "rootType": ObjectTypeDescriptor, "resolvedValues": object }` and writes the `ExecutionResponse` JSON to stdout. Type definitions are in `/app/src/types.ts`. Install Node dependencies with `cd /app && npm install --save-dev tsx typescript`.

Required behavior:

**Non-Null error propagation**: When a Non-Null typed field completes as `null` (from a null value, a `FieldError`, or a failed scalar coercion), the null must propagate upward through the type tree until it reaches the nearest nullable ancestor, which becomes `null`. If propagation reaches the root, `data` must be `null`. Only one error per propagation chain must appear in the errors array — the original error at the leaf path, not intermediate wrappers.

**List completion**: Each list item must be completed individually. Error paths for list items must include the numeric index (e.g., `["items", 1, "val"]`). When a list's item type is Non-Null and an item violates, the entire list resolves to `null`. If the list itself is also Non-Null, propagation continues upward.

**Scalar result coercion** for the five built-in types:
- `Int`: 32-bit signed integer. Reject non-integers and values outside `[-2147483648, 2147483647]`. Accept boolean and numeric string coercion.
- `Float`: IEEE 754 double. Reject non-finite values (NaN, Infinity). Accept boolean and numeric string coercion.
- `String`: Accept strings, coerce booleans and finite numbers to string.
- `Boolean`: Accept booleans, coerce finite numbers (0 → false, nonzero → true).
- `ID`: Accept strings and integers. Integers must be serialized as strings.

**Error format**: Each error must have `message` (string) and `path` (array of string field names and numeric list indices from root to the erroring field).

**Response format**: `{ data, errors? }` — `errors` present only when non-empty.
