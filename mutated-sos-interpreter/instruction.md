The `/app/` directory contains a formal specification of the IMP imperative language:

- `/app/semantics.txt` — 78 inference rules defining the language's small-step operational semantics (SOS) using configurations `〈operation, σ, χ〉` with a store and control stack
- `/app/syntax.txt` — BNF grammar
- `/app/programs/` — 8 IMP source files (`.imp`)

**Critical**: The operators in these rules do *not* necessarily compute what their syntax tokens conventionally suggest. The inference rules are the sole authority on what each operator actually does. Do not assume standard arithmetic, comparison, logical, or unary operator behavior.

Build a complete IMP toolchain in `/app/` that parses and executes all programs faithfully. Your parser must use the PLY library, and running it must produce `/app/parsetab.py`.

**Required outputs:**

- `/app/results/<basename>.json` for each `.imp` file — a JSON object mapping every variable name to its final integer value after execution under the **provided (mutated)** semantics.
- `/app/results_standard/<basename>.json` for each `.imp` file — the same, but executing under **standard IMP semantics** where each operator computes what its token conventionally means in imperative languages (e.g., `+` adds, `<` checks less-than, `&&` computes logical conjunction, unary `-` negates).
- `/app/analysis/mutations.json` — a JSON object with keys `arithmetic`, `comparison`, `logical`, `unary`. Each maps syntax operator strings to the actual operation computed by the provided rules. For binary operators use the corresponding operator string. For unary operators use `"negate"` or `"identity"`.
- `/app/analysis/divergence.json` — for each program (keyed by basename), an object with: `mutated_state` (final state under provided semantics), `standard_state` (final state under standard semantics), `differs` (boolean), and `affected_categories` (sorted list of mutation category names — `arithmetic`, `comparison`, `logical`, `unary` — where the program contains at least one operator from that category whose provided semantics differs from standard).
- `/app/programs/verification.imp` — an IMP program you create containing a variable `check` that evaluates to `1` under the provided semantics and `0` under standard semantics. This program must also be executed and included in both result sets and the divergence analysis.
- `/app/Makefile` with at least these targets: `parse-tables`, `analyze`, `run-mutated`, `run-standard`, `diverge`, `all`.