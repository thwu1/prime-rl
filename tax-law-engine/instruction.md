Internal Revenue Code Section 121 governs the exclusion of gain from the sale of a principal residence. The complete statutory text with all subsections is at `/app/irc_section121.md`. The Python interface specifying data types and the required function signature is at `/app/interface.py`.

Produce the following:

**`/app/tax_engine.py`** — Implement the `compute_exclusion` function declared in `/app/interface.py`. The implementation must faithfully encode every provision and cross-subsection interaction described in the statutory text.

**`/app/formal_verify.py`** — Verify each invariant annotated `[INVARIANT]` in the statutory text and write results to `/app/verification_results.json`. The output must be a JSON array where each element contains `"property"` (invariant name), `"result"` (`"proved"` or `"witness_found"`), and `"solver_result"` (`"unsat"` or `"sat"` respectively).