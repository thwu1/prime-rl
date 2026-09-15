Build CaDiCaL from source at `/app/cadical/` and implement an unweighted Partial MaxSAT solver as an executable at `/app/maxsat`.

The solver must use CaDiCaL's C++ library API (`libcadical.a` / `cadical.hpp`) for all SAT solving — not the command-line binary. It must link against the library you build.

**Input:** The solver reads a single WCNF file path as its command-line argument. WCNF files use the standard format:

```
p wcnf <nvars> <nclauses> <top>
<weight> <lit1> <lit2> ... 0
```

Clauses with weight >= `top` are hard (must be satisfied). Clauses with weight < `top` are soft (each has unit cost when violated). All soft clause weights in the test instances are 1.

**Output:** Print to stdout:

```
s OPTIMUM FOUND
o <cost>
v <lit1> <lit2> ... 0
```

where `<cost>` is the minimum number of violated soft clauses, and the `v` line gives a satisfying assignment for all original variables (positive literal = true, negative = false), terminated by `0`.

If the hard clauses alone are unsatisfiable, print `s UNSATISFIABLE` and exit with code 1.

The solver must produce provably optimal results on all test instances in `/app/instances/`. These instances range up to 16 variables and 40 clauses, and the solver must complete each within 2 minutes.