Build a re-runnable analysis pipeline at `/app/analyze.sh` that reads Jepsen-format EDN operation histories from `/app/histories/`, checks each for linearizability against a compare-and-set register, and produces:

- `/app/results.json` — a JSON object mapping each `.edn` history filename to a boolean linearizability verdict.
- `/app/viz/<name>.dot` and `/app/viz/<name>.svg` — for every **non-linearizable** history, a Graphviz DOT source and its rendered SVG showing operations as labeled nodes and real-time precedence as directed edges.

## CAS Register Model

The register starts at `nil` and supports three operations:
- `read` — returns the current value
- `write v` — sets register to `v` (always succeeds)
- `cas [old, new]` — if current value equals `old`, atomically sets to `new`; otherwise the CAS fails

## EDN History Format

Histories use Clojure EDN notation — not JSON. Each file is a vector of event maps with keys `:index` (sequential), `:process` (integer), `:type` (`:invoke`/`:ok`/`:fail`/`:info`), `:f` (`:read`/`:write`/`:cas`), and `:value`. Operations pair by process: `invoke`→`ok` (completed successfully), `invoke`→`fail` (definitely did not take effect), `invoke`→`info` (process crashed — may or may not have taken effect).

## Linearizability

A history is linearizable if there exists a total ordering of the completed (`ok`) operations — plus any chosen subset of `info` operations — such that (1) real-time precedence is respected (if A's completion event precedes B's invocation event, A must appear before B in the ordering), (2) every operation's result is consistent with the CAS register model applied sequentially, and (3) included `info` operations may linearize anywhere after their invocation.

## Visualization

Each DOT/SVG for a non-linearizable history must show completed operations as labeled nodes (process, function, value, outcome) and real-time precedence as directed edges.

Babashka (`bb`) and Graphviz (`dot`) are installed in the environment. Executing `/app/analyze.sh` must process all `.edn` files currently in `/app/histories/`.