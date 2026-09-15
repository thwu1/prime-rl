A Lean 4 project is set up at `/app/` with Lean 4.16.0 installed and no external dependencies. The file `/app/Reduction.lean` contains a partial formalization of the polynomial-time reduction from Not-All-Equal Satisfiability (NAE-SAT) to 3-Graph-Coloring.

Complete all four `sorry` obligations in `/app/Reduction.lean`:

1. **`EdgeRelation`**: Define the edge relation for the reduction graph. The ground node connects to every variable node. Each variable node connects to the clause gadget node at the position matching the variable's index within that clause. Clause nodes within the same clause that belongs to the clause list form a triangle (all pairs with distinct indices are connected).

2. **`clauseNodeColor`**: Define a function `(a b c : Bool) → (k : Fin 3) → Fin 3` that assigns colors to the three clause gadget nodes based on the truth values of the clause's three variables. The ground node is colored `0`, variables colored `1` (true) or `2` (false). When the clause satisfies NAE (not all equal), the three clause-node colors must be pairwise distinct, and each must differ from the color of its corresponding variable node.

3. **`NAEtoColorCompleteness`**: Prove that if a NAE-SAT instance is satisfiable, then the reduction graph is 3-colorable.

4. **`NAEtoColorSoundness`**: Prove that if the reduction graph is 3-colorable, then the NAE-SAT instance is satisfiable.

The file must compile successfully with `lake build` and contain no remaining `sorry`. Verify with `cd /app && lake build`. Helper lemmas `fin3_cases` and `list_all_mem` are provided; no Mathlib is available.