Four TypeScript type utility files under `/app/src/types/` contain placeholder implementations that return trivial types (`false`, `never`, identity, or empty tuples). Replace them with correct type-level logic so that every type assertion in `/app/tests/type-checks.ts` passes.

**Files to implement (do not rename or move):**

- `/app/src/types/IsMatching.ts` -- Must export `IsMatching<a, b>`. The type-checks file shows the expected behavior across primitives, objects, tuples, unions, and arrays.

- `/app/src/types/BuildMany.ts` -- Must export `BuildMany<data, xs>` and `SetDeep<data, value, path>`. The type-checks file shows the expected behavior for nested object updates, tuple element replacement, and sequential multi-path transforms.

- `/app/src/types/DistributeUnions.ts` -- Must export `DistributeMatchingUnions<a, p>`, `FindUnionsMany`, `FindUnions`, and `Distribute`. Must import and use `BuildMany` from `./BuildMany` and `IsMatching` from `./IsMatching`. The type-checks file demonstrates expected distribution results.

- `/app/src/types/DeepExclude.ts` -- Must export `DeepExclude<a, b>`. Must import and use `DistributeMatchingUnions` from `./DistributeUnions`. The type-checks file contains ~80 assertions covering primitives, literals, objects, tuples, variadic arrays, Sets, Maps, readonly types, optional properties, union patterns, and multi-pattern exclusion.

**Provided files (do not modify):**

- `/app/src/types/helpers.ts` -- Type utilities available for import (`Equal`, `Expect`, `IsUnion`, `UnionToTuple`, `Flatten`, `Values`, `UpdateAt`, `Iterator`, `IsPlainObject`, `IsLiteral`, `ValueOf`, `MaybeAddReadonly`, `IsStrictArray`, `IsReadonlyArray`, `IsOptionalKeysOf`, `IsAny`, etc.).
- `/app/tests/type-checks.ts` -- All type assertions (the specification).
- `/app/tests/utils.ts` -- Test helper types (`Option`, `State`, `BigUnion`).

**Setup:** Run `npm install` in `/app`.

**Verification:** `npx tsc --noEmit` in `/app` must exit with code 0. All `Expect<Equal<...>>` assertions and all `@ts-expect-error` annotations must hold.
