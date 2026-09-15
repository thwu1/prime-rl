Solve edge-reversal reachability problems on Nondeterministic Constraint Logic (NCL) constraint graphs. For unreachable instances, construct machine-verifiable certificates validated by the Z3 theorem prover. Generate Graphviz visualizations of all instances.

## Model

A **constraint graph** is an undirected graph where each edge has a positive integer weight and each vertex has a minimum inflow constraint. A **configuration** assigns a direction to every edge. A configuration is **valid** when each vertex's total incoming weight meets or exceeds its minimum inflow. A **move** reverses exactly one edge; a move is legal only if the resulting configuration is valid.

**Edge-reversal reachability**: given a valid initial configuration, a target edge, and a target direction, determine whether any sequence of legal moves leads to a configuration where the target edge points in the target direction.

## Input

Instance files at `/app/instances/*.json`:

```json
{
  "vertices": {"vid": {"min_inflow": N}, ...},
  "edges": {"eid": {"endpoints": ["u", "v"], "weight": W}, ...},
  "initial_orientation": {"eid": "vertex_it_points_toward", ...},
  "target_edge": "eid",
  "target_direction": "vid"
}
```

An edge oriented toward vertex `v` contributes its weight to `v`'s inflow.

## Required Output

**`/app/results.json`** — Reachability verdicts and witness paths, keyed by instance name (filename without `.json`):

```json
{"instance_name": {"reachable": bool, "path": ["eid1", ...] or null}}
```

Each entry in `path` names an edge to reverse. Every reversal must be legal from the configuration at that point in the sequence. Use `null` for unreachable instances.

**`/app/invariants/{name}.json`** — For each **unreachable** instance, a certificate:

```json
{"fixed_edges": {"eid": "vertex_it_must_point_toward", ...}}
```

The certificate must satisfy all of the following:
- Every listed edge matches its orientation in the initial configuration.
- No listed edge can be legally reversed in any valid configuration where all listed edges maintain their listed orientations.
- The target edge is listed, pointing in a direction other than the target direction.

**`/app/proofs/{name}.smt2`** — For each **unreachable** instance, a standalone SMT-LIB2 script. Running `z3 /app/proofs/{name}.smt2` must produce only `unsat` lines. The script must model the instance's graph structure.

**`/app/graphs/{name}.dot`** — A Graphviz DOT digraph for each instance. Weight-1 edges colored red, weight-2 edges colored blue. Each edge labeled with its ID and weight.

**`/app/graphs/{name}.svg`** — SVG rendering of each DOT file via `dot -Tsvg`.