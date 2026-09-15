Build `/app/mc`, a compiled native binary (not an interpreted script) that performs exact model counting on DIMACS CNF formulas using the Model Counting Competition format.

**Invocation**: `/app/mc <input.cnf>`

**Input format**: MC Competition DIMACS CNF with track and weight directives. Examine the benchmark instances in `/app/benchmarks/` for comprehensive format examples covering both unweighted and weighted tracks, including weight specifications in various numeric representations (fractions, decimals, scientific notation). Default to unweighted counting (`mc`) if no track directive is present. Default weight for any unspecified literal is `1`.

**Required output** (stdout):
- Line: `s SATISFIABLE` or `s UNSATISFIABLE`
- Line: `c s type mc` or `c s type wmc` (matching the input track)
- For `mc` track: `c s exact arb int <N>` — exact integer count of satisfying assignments
- For `wmc` track: `c s exact rational <P>/<Q>` — exact weighted count as an irreducible fraction

**Weighted model counting**: the weighted count is the sum over all satisfying assignments of the product of the literal weights selected by each assignment.

**Edge cases**:
- UNSAT formulas: count is `0` (output `0` or `0/1` as appropriate)
- Zero clauses: every assignment satisfies; count is the product of per-variable contributions
- Free variables (declared in the problem line but absent from all clauses) multiply the count by their contribution

**Precision**: All arithmetic must be exact and arbitrary-precision — counts may exceed 2^64.

**Performance**: Must produce correct results within 60 seconds for formulas with up to 50 variables, including formulas with independent subproblems spanning 40+ total variables.

A build-ready Makefile is provided at `/app/Makefile`. GMP development headers and libraries (`libgmp-dev`) are installed.
