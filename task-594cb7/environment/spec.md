# Jepsen History Consistency Checker — Specification

## Input Format

Each file in `/app/histories/` is a Jepsen operation history in EDN (Extensible Data Notation) format. EDN is Clojure's data notation; you will need an appropriate parser to read it.

A history is a vector of operation maps, ordered by `:index`:

```edn
[{:index 0 :type :invoke :f :txn :value [[:append 5 1] [:r 3 nil]] :process 0 :time 1000000}
 {:index 1 :type :ok :f :txn :value [[:append 5 1] [:r 3 [1 2]]] :process 0 :time 5000000}
 ...]
```

Each operation has:
- `:index` — sequential operation number
- `:type` — one of `:invoke`, `:ok`, `:fail`, `:info`
- `:f` — always `:txn` (transaction)
- `:value` — vector of micro-operations
- `:process` — the client process that issued this operation
- `:time` — wall-clock timestamp in nanoseconds

Operations come in pairs per process: an `:invoke` is followed by its completion (`:ok`, `:fail`, or `:info`). A process has at most one outstanding invocation at a time.

- `:ok` — transaction committed successfully
- `:fail` — transaction definitely did not commit
- `:info` — outcome unknown (e.g., timeout)

Only `:ok` transactions represent committed work and should be included in the analysis.

### Micro-operations

Each transaction's `:value` contains micro-operations:
- `[:append key value]` — appends a unique integer value to a list-valued key
- `[:r key observed]` — reads a key; in `:invoke` operations `observed` is `nil`; in `:ok` operations it contains the observed list (may be empty `[]`)

Keys are integers. Each appended value is globally unique across the entire history.

## Analysis Requirements

### Transaction Extraction

Extract committed transactions by matching `:invoke`/`:ok` pairs by process. Discard `:fail` and `:info` outcomes. Assign each committed transaction a sequential ID starting from 0.

### Version Order Inference

For each key, determine the order in which values were appended by examining read observations. The longest read of a key establishes the canonical ordering of appended values. Values not observed in any read are appended at the end in sorted order.

### Dependency Graph Construction

Build four types of directed dependency edges between committed transactions:

- **WW (write-write)**: For consecutive writes to the same key in version order, `T_i → T_j` means `T_i`'s write precedes `T_j`'s write.
- **WR (write-read)**: `T_i → T_j` means `T_j` read a value that `T_i` wrote.
- **RW (read-write / anti-dependency)**: `T_i → T_j` means `T_i` read a version of a key, and `T_j` wrote the next version after it. If `T_i` read an empty list for a key, `T_j` is the first writer of that key.
- **RT (real-time)**: `T_i → T_j` means `T_i` completed (`:ok`) before `T_j` was invoked.

### Anomaly Detection

Detect cycles in progressively larger edge sets:

- **G0 (dirty write)**: cycle exists in **WW** edges only
- **G1c (circular information flow)**: cycle exists in **WW ∪ WR** edges
- **G2 (anti-dependency cycle)**: cycle exists in **WW ∪ WR ∪ RW** edges
- **Strict serializability violation**: cycle exists in **WW ∪ WR ∪ RW ∪ RT** edges

### Consistency Level Classification

From strongest to weakest:

| Level | Condition |
|---|---|
| strict-serializable | No cycles in WW ∪ WR ∪ RW ∪ RT |
| serializable | No cycles in WW ∪ WR ∪ RW, but cycle in WW ∪ WR ∪ RW ∪ RT |
| read-committed | Cycle in WW ∪ WR ∪ RW but not in WW ∪ WR |
| read-uncommitted | Cycle in WW ∪ WR but not in WW |
| anomalous | Cycle in WW |

### Graph Analysis

For the combined **WW ∪ WR ∪ RW** dependency graph:

1. **Edge counts**: Count the distinct edges for each type (WW, WR, RW).
2. **Strongly Connected Components (SCCs)**: Compute SCCs using Tarjan's algorithm. Count the number of non-trivial SCCs (those with more than one node). Report the size of the largest SCC.
3. **Shortest anomaly cycle**: For the strongest anomaly present (G0 uses WW; G1c uses WW ∪ WR; G2 uses WW ∪ WR ∪ RW), find the shortest cycle. If multiple shortest cycles exist, report the lexicographically smallest one (by transaction ID sequence). The cycle is represented as a list of transaction IDs ending with the first ID repeated (e.g., `[2, 5, 2]`).
4. **Minimum Feedback Vertex Set (MFVS)**: Compute the minimum set of transaction IDs whose removal from the WW ∪ WR ∪ RW graph breaks all cycles. If multiple minimal sets exist, report the lexicographically smallest one.

### Graph Visualization

For each history where any anomaly (G0, G1c, or G2) is detected, produce an SVG visualization at `/app/graphs/<history_name>.svg` using graphviz. The graph should depict the shortest anomaly cycle with nodes representing transactions and labeled edges showing the dependency type.

## Output Format

Write to `/app/results.json`:

```json
{
  "<history_name>": {
    "committed_count": <int>,
    "consistency_level": "<level>",
    "g0": <boolean>,
    "g1c": <boolean>,
    "g2": <boolean>,
    "strict_serializable": <boolean>,
    "edge_counts": {
      "ww": <int>,
      "wr": <int>,
      "rw": <int>
    },
    "shortest_cycle": [<int>, ...] or null,
    "scc_count": <int>,
    "scc_max_size": <int>,
    "min_removal_count": <int>,
    "min_removal_set": [<int>, ...]
  }
}
```

Where `<history_name>` is the filename without extension (e.g., `"h1"` for `h1.edn`).

Fields:
- `committed_count`: number of committed (`:ok`) transactions
- `consistency_level`: strongest consistency level from the table above
- `g0`, `g1c`, `g2`: whether the respective anomaly was detected
- `strict_serializable`: whether the history admits a strict-serializable ordering
- `edge_counts`: count of distinct directed edges for each dependency type
- `shortest_cycle`: transaction IDs forming the shortest anomaly cycle (or `null` if no anomalies)
- `scc_count`: number of strongly connected components with >1 node in WW ∪ WR ∪ RW graph
- `scc_max_size`: size of the largest non-trivial SCC (0 if none)
- `min_removal_count`: size of the minimum feedback vertex set for WW ∪ WR ∪ RW graph
- `min_removal_set`: the minimum feedback vertex set (sorted, lexicographically smallest)
