A partially implemented type-safe extensible record library exists at `/app/`. It uses GADTs and type families to provide type-indexed heterogeneous records.

`/app/FCF.hs` is a complete, working first-class families library. Do not modify it.

`/app/ExtensibleRecord.hs` contains core type definitions and several broken or stubbed operations. Fix and complete this module so that all tests pass.

**Required operations on `OpenProduct f ts`:**

- `insert`: Prepend a key-value pair. Must reject duplicate keys at compile time via a custom `TypeError` that names the conflicting key, its existing type, and suggests using `upsert`.
- `get`: Retrieve a value by its type-level `Symbol` key.
- `update`: Replace a value at a key, possibly changing its type. The result type list must reflect the new type.
- `delete`: Remove a field by key. The result type list must exclude that key.
- `upsert`: Insert if the key is absent, update if present. The result type must reflect whichever case occurred.
- `peel`: Destructure the first field off a non-empty product, returning the value and the remaining product.
- `merge`: Combine two products whose key sets are disjoint. Must reject overlapping keys at compile time.
- `Eq` instances for both empty and non-empty products (base case and inductive step).

**Constraints:**
- The internal representation and type-level machinery are already partially defined in the skeleton. Study the existing code, the FCF library, and the type signatures to determine what each stub or broken definition should do.
- Do not change any type signatures, data type definitions, or the `insert` function body — only fix type families, implement term-level stubs, and add missing instances/definitions.

**Success criteria:**
1. `ghc -i/app -odir /tmp/ghc_out -hidir /tmp/ghc_out -o /tmp/test_record /tests/TestDriver.hs` compiles without errors.
2. `/tmp/test_record` runs and outputs `ALL TESTS PASSED`.
3. Code that attempts to `insert` a duplicate key fails to compile with a descriptive type error.
4. Code that attempts to `merge` products with overlapping keys fails to compile.
