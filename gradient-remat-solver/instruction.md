Deliver a working gradient rematerialization solver at `/app/rematerialization/solver.py` that integrates the C shared library at `/app/rematerialization/dp_core.c`.

`/app/rematerialization/` contains a `Chain` data model (`chain.py`), operation types with documented semantics (`ops.py`), a C source file (`dp_core.c`) with a `Makefile`, and an empty `__init__.py`. The C source compiles but contains defects that cause it to produce incorrect results. The `Makefile` is correct.

**Required deliverables:**

1. Fix `/app/rematerialization/dp_core.c` so it produces correct optimization values, then build `/app/rematerialization/dp_core.so` using the provided `Makefile`.

2. Create `/app/rematerialization/solver.py` exporting three functions:

   `compute_table(chain, mmax)` -- Returns `(opt, what)`. `opt[m][i]` must be a dict-like object mapping `l` to float cost values, for `m` in `[0, mmax]`, `i` in `[0, chain.length]`, `l` in `[i, chain.length]`. The `what` component encodes the corresponding scheduling decisions. This function must load and call the compiled `dp_core.so`.

   `reconstruct(chain, lmin, lmax, cmem, opt_table)` -- Given the output of `compute_table`, produce a flat list of operation objects (types from `/app/rematerialization/ops.py`) representing a valid schedule for processing subchain `[lmin, lmax]` with available memory `cmem`. At the top level, `cmem = mmax - chain.cweigth[0]`.

   `simulate(ops, chain)` -- Given a list of operations and a chain, return peak memory usage as an integer. Memory starts containing only `x_0`. Must raise `ValueError` when any operation's preconditions are violated (see `ops.py` docstrings for semantics).

**Correctness requirements:**

- The total computation time of a reconstructed sequence must equal `opt[cmem][0][chain.length]`.
- Simulated peak memory of any reconstructed sequence must not exceed the original budget.
- `opt[m][i][l]` must be monotonically non-increasing in `m` for fixed `(i, l)`.
- With a sufficiently large budget, makespan must equal `sum(fweigth) + sum(bweigth)`.
- Must produce correct results on heterogeneous chains where all layer costs differ.
- `/app/rematerialization/dp_core.so` must exist as a compiled shared library.
