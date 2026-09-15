A *magma* is a set S equipped with a binary operation ◇ : S × S → S. An operation table of *order n* represents a magma on {0, …, n−1} as an n×n matrix M where M[i][j] = i ◇ j. An equation holds in a magma when satisfied for every assignment of elements to variables. Equation Ei *implies* Ej (over magmas of order ≤ k) when every magma of order ≤ k satisfying Ei also satisfies Ej.

The file `/app/equations.json` defines 10 equational laws for magmas using `*` for the binary operation and single-letter variables. Analyze the complete implication structure over all magmas of order ≤ 4 and produce the following files in `/app/results/`:

- **`spectrum.json`** — Map equation ID → `[count_1, count_2, count_3]` where `count_k` is the number of order-k magmas satisfying the equation.

- **`joint_spectrum.json`** — Nested map where `["Ei"]["Ej"]` is the number of order-3 magmas satisfying both Ei and Ej simultaneously.

- **`implications.json`** — Map equation ID → sorted list of all equation IDs it implies over magmas of order ≤ 4 (including self-implication).

- **`counterexamples.json`** — For each ordered pair (Ei, Ej) with i ≠ j where Ei does NOT imply Ej, key `"Ei->Ej"` → `{"order": <int>, "table": <2D list>}` — a magma of smallest possible order satisfying Ei but not Ej. Table entries must be integers in `[0, order)`.

- **`hasse.json`** — Transitive reduction of the implication graph, excluding self-loops. Map equation ID → sorted list of directly-implied equation IDs.

- **`duality.json`** — Map equation ID → `{"dual_id": <string or null>, "self_dual": <bool>}`. The *dual* of an equation is obtained by recursively swapping the two children of every binary-operation node throughout the equation's syntax tree, then checking whether the resulting equation matches any equation in the set up to variable renaming. `dual_id` is the ID of the matching equation, or null if none matches. `self_dual` is true when the equation is its own dual.

- **`hasse.dot`** — Hasse diagram as a Graphviz DOT digraph. Each equation is a node labeled with its ID and name. Directed edges represent covering relations in the implication order (from the stronger/more-restrictive equation to the weaker/more-general one it directly implies).

- **`hasse.svg`** — Hasse diagram rendered to SVG using the Graphviz `dot` layout engine.

- **`lattice_properties.json`** — `{"width": <int>, "height": <int>, "num_maximal": <int>, "num_minimal": <int>, "num_connected_components": <int>}`. Width = maximum antichain size in the implication poset. Height = number of edges in the longest chain. Maximal/minimal elements are with respect to the implication ordering (Ei ≤ Ej iff Ei implies Ej). Connected components are those of the undirected Hasse graph.

There are 4^(4²) = 4,294,967,296 distinct order-4 operation tables.