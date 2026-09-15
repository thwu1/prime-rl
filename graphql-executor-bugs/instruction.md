A GraphQL execution engine at `/app/src/executor.ts` must produce spec-compliant `ExecutionResult` JSON. It uses `graphql` v16.8.1 for parsing but implements its own execution. Install: `cd /app && npm install`.

CLI at `/app/src/cli.ts` accepts a JSON file path with `schema` (SDL), `query`, `rootValue` (property-lookup resolver), optional `variables`. Outputs `ExecutionResult` JSON on stdout.

`ExecutionResult`: `data` (result object or `null` on root propagation), `errors` (array of `{message, path}` where path contains response-name strings and 0-indexed list positions).

Required execution semantics:

**Non-Null enforcement**: Null in Non-Null field records an error and propagates null upward through Non-Null boundaries to the nearest nullable ancestor. All Non-Null to root makes `data` null.

**List completion**: Elements completed independently with 0-indexed path entries. Non-Null element type with null element triggers propagation to the list.

**Fragment collection**: Inline fragments and named fragment spreads collected. Type conditions checked via object-name equality, interface implementation, and union membership.

**Abstract type resolution**: Interface/union fields resolve runtime type via `__typename` on the source object.

**Response naming**: Aliases used as response keys and in error paths.

**Directive handling**: `@skip(if: true)` excludes; `@include(if: false)` excludes. Both may coexist; `@skip` evaluated first, takes precedence. Applies to fields, inline fragments, and fragment spreads.

**Variable resolution**: `$varName` references resolved from the variables map. Operation-defined defaults apply when a variable is not provided.

**Scalar serialization**: Leaf values coerced through scalar type serialization: `42` on String becomes `"42"`, `1` on Boolean becomes `true`, `123` on ID becomes `"123"`.

**Resolver value integrity**: Falsy values (`0`, `false`, `""`) are valid results, not nulls.

**Field argument resolution**: Extract argument values from the query AST, resolve variable references within them, apply schema-defined argument defaults for omitted arguments. If the source value for the field is a function, invoke it with the coerced arguments `(args: Record<string, unknown>) => unknown` and use the return value. Non-function values returned directly regardless of arguments.

Invocation: `npx tsx /app/src/cli.ts /path/to/input.json`
