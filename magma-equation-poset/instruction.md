A magma is a set equipped with a single binary operation `*`. The file `/app/equations.json` defines 8 equational laws as term ASTs: each term is either a variable name (string) or `{"op": "*", "args": [left, right]}`. Each equation has `lhs`, `rhs`, `vars`, `display`, and `name` fields. The file `/app/magmas.json` defines 5 reference magmas as operation tables (`table[i][j]` = result of `i * j`).

A magma **satisfies** an equation iff the equation holds under every assignment of elements to variables. Equation A **implies** equation B over size-n magmas iff every size-n magma satisfying A also satisfies B. Two magmas on `{0,...,n-1}` are **isomorphic** iff there exists a permutation `sigma` of `{0,...,n-1}` such that `T'[sigma(i)][sigma(j)] = sigma(T[i][j])`. The **Hasse diagram** of a partial order contains an edge from A to B iff A strictly implies B (A implies B but not vice versa) and no intermediate C exists with A strictly implying C and C strictly implying B.

Produce the following 6 output files in `/app/results/`. All results must be mutually consistent — counterexample magmas must genuinely satisfy their premise and violate their conclusion, the implication matrix must agree with counterexample data, and database contents must match the JSON outputs.

**`z3_counterexamples.json`** — For each of the 56 ordered pairs `(Ei, Ej)` with `i != j`, a magma of minimal size (among sizes 2 and 3) that satisfies Ei but violates Ej, or `null` if no such magma exists at size <= 3 (meaning the implication holds). Format: `{"E1->E2": {"size": 2, "table": [[...], ...]}, "E1->E3": null, ...}`

**`iso_classes.json`** — The total number of distinct isomorphism classes among all `3^9 = 19683` size-3 operation tables, and for each equation, the count of isomorphism classes containing at least one table satisfying that equation. Format: `{"total_classes": <int>, "per_equation": {"E1": <int>, ...}}`

**`implications.json`** — For all 64 ordered pairs `(Ei, Ej)`, whether Ei implies Ej over size-3 magmas. Format: `{"E1->E1": true, "E1->E2": false, ...}`

**`hasse.json`** — The Hasse diagram of the strict implication partial order over size-3 magmas. Format: `{"E1": ["E6", ...], ...}` with sorted successor lists.

**`hasse.svg`** — An SVG rendering of the Hasse diagram. Each node labeled with equation ID and display formula. Edges represent cover relations.

**`magma_theory.db`** — SQLite database with tables:
- `equations(id TEXT PRIMARY KEY, name TEXT NOT NULL, display TEXT NOT NULL, num_vars INTEGER NOT NULL)`
- `implications(premise_id TEXT NOT NULL, conclusion_id TEXT NOT NULL, holds INTEGER NOT NULL, counterexample_size INTEGER, counterexample_table TEXT, PRIMARY KEY(premise_id, conclusion_id))`
- `iso_class_stats(equation_id TEXT PRIMARY KEY, num_satisfying_classes INTEGER NOT NULL, num_satisfying_tables INTEGER NOT NULL)`