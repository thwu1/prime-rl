Build an incremental Datalog evaluator as a Python script at `/app/datalog.py`. The evaluator must correctly maintain derived relations under both insertions and deletions of base facts, and must support stratified negation.

The evaluator must handle:
- Recursive rules with cyclic derivations (transitive closure over graphs with cycles, producing self-reachability)
- Multi-predicate programs where derived relations depend on other derived relations (e.g., SCC detection built on reachability)
- Rules with three or more body atoms requiring multi-way joins (e.g., directed triangle enumeration)
- **Stratified negation**: body atoms prefixed with `not` reference predicates that must be fully evaluated in a lower stratum before the negating rule fires
- Correct maintenance under deletions: derived facts still derivable through alternative paths must be preserved

## CLI Interface

```
python3 /app/datalog.py --rules <path> --facts <path> --updates <path> --query <predicate>
```

Write JSON-lines to stdout. Each line is a JSON object with `"batch"` (integer, 0 for the initial state before any updates) and `"tuples"` (sorted list of integer lists representing ground tuples in the queried relation):

```
{"batch": 0, "tuples": [[1, 2], [1, 3], [2, 3]]}
{"batch": 1, "tuples": [[1, 2]]}
```

Tuples must be sorted in lexicographic order.

## File Formats

**Rules** (`rules.dl`): One Datalog rule per line. Variables are uppercase identifiers. `not` before a body atom indicates negation. Lines starting with `%` are comments.
```
reach(X, Y) :- edge(X, Y).
reach(X, Y) :- reach(X, Z), edge(Z, Y).
disconnected(X, Y) :- node(X), node(Y), not reach(X, Y).
```

**Facts** (`facts.dl`): One ground atom per line. Values are non-negative integers.
```
edge(1, 2).
node(1).
```

**Updates** (`updates.dl`): Batches delimited by `---`. Within each batch, `+` inserts and `-` deletes a base fact.
```
---
+edge(3, 4).
-edge(1, 2).
---
+edge(5, 6).
```

## Test Data

Five scenarios at `/data/`: `reach/`, `cycle/`, `scc/`, `triangle/`, `negation/`. Each contains `rules.dl`, `facts.dl`, `updates.dl`.