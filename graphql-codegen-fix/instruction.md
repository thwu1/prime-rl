A GraphQL-to-TypeScript code generator at `/app/src/generator.ts` produces incorrect TypeScript type definitions from a GraphQL schema and operation documents. After running `npm install` in `/app`, execute `npx tsx /app/src/codegen.ts` to generate `/app/generated/types.ts`.

The schema is at `/app/schema.graphql` and operations are in `/app/operations/*.graphql`. Configuration (including custom scalar mappings) is in `/app/codegen.config.json`.

The generated output must satisfy all of the following:

**Fragment spreads**: `...FragmentName` in a selection set must resolve to include all fields defined in the named fragment. Fragment fields must be merged into the enclosing type.

**Union/interface discrimination**: When inline fragments (`... on TypeName`) appear on a union or interface return type, the output must be a TypeScript discriminated union with a `__typename` string literal for each branch (e.g., `{ __typename: 'User'; ... } | { __typename: 'Post'; ... }`). Shared fields from the parent interface must appear in every branch.

**Field aliases**: When a field uses an alias (`alias: fieldName`), the generated type key must be the alias, not the original field name.

**Conditional directives**: Fields annotated with `@skip(if: ...)` or `@include(if: ...)` must be optional (`?:`) in the generated type.

**@oneOf input types**: Input types with the `@oneOf` directive must produce an exclusive union: each variant has exactly one required field and all others typed as `never` (e.g., `{ id: string; email?: never } | { id?: never; email: string }`).

**List nullability**: The nullability of list items must reflect GraphQL NonNull wrappers: `[T!]!` produces `Array<T>`, `[T]!` produces `Array<T | null>`, `[T!]` produces `Array<T> | null`, `[T]` produces `Array<T | null> | null`. This applies to both scalar/enum leaf types and object types within lists.

**Compilation**: `/app/generated/types.ts` must compile with `npx tsc --noEmit --strict`.

**Success**: `bash /tests/test.sh` writes `1.0` to `/logs/verifier/reward.txt`.
