Implement an expression optimizer at `/app/optimize.py` that finds minimum-cost equivalent expressions using equality saturation, with LLVM IR code generation and formal equivalence proofs.

**Invocation**: `python3 /app/optimize.py <expression_file>` — reads an S-expression from the given file, prints the optimized S-expression to stdout, and writes additional output files to `/app/output/`.

**Expression language**: prefix S-expressions with binary operators (`+`, `-`, `*`, `/`, `<<`, `>>`), unary operator `neg`, integer literals, and variable names (alphabetic strings). Example: `(* (+ a b) 4)`.

**Provided files in `/opt/eqsat/`**:
- `rules.json` — semantics-preserving rewrite rules with pattern variables (`?a`, `?b`, etc.).
- `cost_model.json` — operator costs. Expression cost = sum of operator costs (variables and constants cost 0).
- `benchmarks/` — ten input files (`expr01.sexp` through `expr10.sexp`).

**Required outputs for each benchmark `exprNN.sexp`**:

1. **Stdout**: optimized S-expression — semantically equivalent to input, minimum achievable cost under the rewrite rules plus constant folding.

2. **`/app/output/exprNN.ll`**: LLVM IR text file defining a function `@optimized` that computes the optimized expression. Parameters must be `i64` typed, named after the expression's variables in alphabetical order. The IR must be structurally valid — accepted by the LLVM verifier without errors.

3. **`/app/output/exprNN.smt2`**: SMT-LIB2 script using QF_BV logic (64-bit bitvectors) that encodes the negation of equivalence between the original and optimized expressions. Running `z3` on this file must return `unsat`, formally proving the two expressions are equivalent for all possible variable assignments.

**Pre-installed tools**: LLVM 18 (`opt`, `llc`, `lli`, `llvm-as`, `llvm-dis`), Z3 SMT solver (`z3`).

The rule set includes commutativity, associativity, and distributivity — greedy term-rewriting will fail due to phase-ordering on several benchmarks.