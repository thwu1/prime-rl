The project at `/app/` implements a query plan optimizer inspired by Apache Spark's Catalyst framework. Compile and test via `make build` and `make test` from `/app/`. Final verification compiles `/tests/TestRunner.java` alongside `/app/src/*.java` and runs `TestRunner`.

All 22 tests currently fail. Make every test pass.

**Project layout:**
- `/app/src/` — Java source: expression AST, logical plan tree, rule engine, configuration loader, optimization rule stubs
- `/app/Makefile` — build and test targets
- `/app/config/optimizer.properties` — rule engine batch configuration
- `/tests/TestRunner.java` — test harness (do not modify)

**Required optimizer behaviors:**

*Constant folding*: foldable deterministic sub-expressions evaluate to literal values. Null arithmetic propagates nulls. Division by zero yields a null literal.

*Boolean simplification*: simplify under SQL three-valued NULL semantics — identity/annihilator with TRUE/FALSE, double negation elimination, idempotence, absorption, complement elimination (non-nullable operands only), common factor extraction across OR-of-ANDs.

*Null propagation*: `IsNull` on a non-nullable expression resolves to `FALSE`; `IsNotNull` on a non-nullable expression resolves to `TRUE`. Nullable expressions remain unchanged.

*Predicate pushdown*: a filter above a join decomposes AND-conjuncts and pushes single-side-referencing deterministic predicates into the corresponding join child. Cross-referencing and non-deterministic predicates stay above.

*Rule engine*: batch execution supports both single-pass and iterate-until-stable modes. Rules apply across the entire plan tree.

All 22 tests must pass.
