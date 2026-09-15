A hierarchical network traffic shaper library is implemented in `/app/shaper.c` (with header `/app/shaper.h`). It compiles with `make -C /app` but does not conform to its specification.

The specification is at `/app/SPEC.md`. The implementation has three categories of defects:

1. **Validation bugs**: Several input-validation and constraint-enforcement checks are missing or inverted. These bugs interact — fixing one may reveal another that was previously masked.

2. **Broken implementation**: `shaper_compact()` contains an implementation that compiles and appears plausible but produces corrupt tree state under certain node layouts. Evaluate its correctness against the specification and determine what invariant it violates.

3. **Missing algorithm**: `shaper_rebalance()` is a no-op stub. The specification defines only the invariants and properties the algorithm must satisfy — not the procedure itself. Design and implement a correct algorithm that meets all stated properties.

Internal diagnostic routines in the code may themselves contain errors, so relying on them for debugging can produce misleading results.

Fix `/app/shaper.c` so that the full test suite passes. Do not modify any other files.