A Rust project at `/app/` contains a symbolic expression library (`src/lib.rs`) with an `Expr` AST type, an `eval` function, and a `simplify` function that applies algebraic simplifications. The `quickcheck` crate is included as a dependency.

The `simplify` function contains multiple correctness bugs: it produces expressions that evaluate to different values than their unsimplified forms under certain inputs. Your task:

1. Implement `Arbitrary` and a custom `shrink` for the `Expr` type (in `src/lib.rs`) to enable property-based testing. Generation must be size-bounded to prevent unbounded recursion. Shrinking must produce structurally smaller expressions.

2. Write QuickCheck property-based tests in `/app/tests/properties.rs` that use evaluation as an oracle to detect the bugs: for any expression `e` and environment, `eval(simplify(e), env)` must equal `eval(e, env)`. Also test that simplification is idempotent: `simplify(simplify(e)) == simplify(e)`.

3. Find and fix all correctness bugs in `simplify` so that both your property tests and the project's full test suite pass (`cargo test`).