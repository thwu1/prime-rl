Implement the `solve_prop` tactic in `/app/IPL.v` within the `IPLSolver` module. This tactic must provide automated depth-bounded proof search for intuitionistic propositional logic (IPL), written entirely in Ltac2.

**Required interface (inside `Module IPLSolver`):**

- `Ltac2 rec solve_prop (depth : int) : unit` -- When `depth` reaches 0, the tactic must fail with a backtracking exception. On positive depth, it attempts to close the current goal.
- `Ltac2 ipl_auto () : unit` -- Calls `solve_prop 20`.

**Supported connectives:**

Goals and hypotheses may involve `/\`, `\/`, `->`, `~` (negation, i.e. `not`), `<->`, `True`, and `False`.

**Correctness requirements:**

- Must prove all intuitionistically valid propositional tautologies involving the supported connectives (e.g., conjunction commutativity, De Morgan laws, currying equivalence, iff transitivity, disjunction elimination, double negation introduction, contrapositive).
- Must fail cleanly on goals that are classically valid but intuitionistically unprovable: excluded middle (`A \/ ~A`), double negation elimination (`~~A -> A`), and Peirce's law (`((A -> B) -> A) -> A`).
- Must respect depth bounds: a long implication chain requiring many steps must succeed at high depth (e.g., `solve_prop 15`) but fail at low depth (e.g., `solve_prop 3`).
- Must not use Ltac1 compatibility features. The implementation must be pure Ltac2.

**Compilation:**

```
cd /app && coqc -Q . IPL IPL.v
```

**Files:**

- `/app/IPL.v` -- The only file to modify. A skeleton with the module structure and stubs is already present.
- `/app/_CoqProject` -- Coq project configuration (do not modify).

**Verification:**

A test Coq file is compiled against the built `IPL.vo`. It applies `solve_prop`/`ipl_auto` to ~30 goals spanning basic through advanced propositional reasoning. Negative tests use Coq's `Fail` command to assert that classically-valid-but-intuitionistically-invalid goals are rejected. Depth-bound tests verify correct termination behavior.
