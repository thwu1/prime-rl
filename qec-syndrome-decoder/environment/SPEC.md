# QEC Decoder Pipeline Specification

## DetectorErrorModel (DEM) Format

A Stim `DetectorErrorModel` describes the error mechanisms in a quantum error correcting code. You can construct one from a string:

```python
dem = stim.DetectorErrorModel("""
    error(0.1) D0 D3 L0 L1 ^ D1 D2 L1
    error(0.2) D0 D3 L0 L1
""")
```

or from a file: `dem = stim.DetectorErrorModel.from_file(path)`.

### Iterating Instructions

Use `dem.flattened()` to iterate over all instructions (this expands `repeat` blocks). Each instruction has:

- `instruction.type` — string: `"error"`, `"detector"`, or `"logical_observable"`
- `instruction.args_copy()` — list of floats; for `"error"` type, this is `[probability]`
- `instruction.targets_copy()` — list of `DemTarget` objects

Each `DemTarget` `t` has:
- `t.is_relative_detector_id()` — True if target is a detector (e.g. D0)
- `t.is_logical_observable_id()` — True if target is an observable (e.g. L0)
- `t.is_separator()` — True if target is the `^` separator
- `t.val` — integer index of the detector or observable

Properties: `dem.num_detectors` (max detector index + 1), `dem.num_observables` (max observable index + 1).

### Separator Semantics

The `^` separator decomposes a hyperedge error mechanism into constituent edge components. For example:

```
error(0.1) D0 D3 L0 L1 ^ D1 D2 L1
```

Has two components separated by `^`:
- Component 1: detectors `{0, 3}`, observables `{0, 1}`
- Component 2: detectors `{1, 2}`, observables `{1}`

The overall **hyperedge** spans:
- Detectors: symmetric difference (XOR) of all component detector sets = `{0, 3} Δ {1, 2}` = `{0, 1, 2, 3}`
- Observables: symmetric difference of all component observable sets = `{0, 1} Δ {1}` = `{0}`

## DemMatrices Dataclass

### Fields

All matrices use `scipy.sparse.csc_matrix` with `numpy.uint8` data type.

- **`check_matrix`**: shape `(num_detectors, num_hyperedges)` — column `j` has 1s at detector rows belonging to hyperedge `j`
- **`observables_matrix`**: shape `(num_observables, num_hyperedges)` — column `j` has 1s at observable rows flipped by hyperedge `j`
- **`edge_check_matrix`**: shape `(num_detectors, num_edges)` — like `check_matrix` but only for edges (components with ≤2 detectors)
- **`edge_observables_matrix`**: shape `(num_observables, num_edges)` — like `observables_matrix` but for edges
- **`hyperedge_to_edge_matrix`**: shape `(num_edges, num_hyperedges)` — column `j` has 1s at edge rows composing hyperedge `j`
- **`priors`**: shape `(num_hyperedges,)` — merged error probability for each hyperedge

### Column Ordering

Hyperedge columns are ordered by first appearance when iterating through `dem.flattened()`. Two hyperedges are considered the same if they have the same detector set (after XOR). Edge columns are similarly ordered by first appearance.

### Probability Merging

When the same hyperedge (identical detector set after symmetric difference) appears across multiple `error` instructions, merge probabilities using:

```
p_merged = p_old × (1 - p_new) + p_new × (1 - p_old)
```

This is applied sequentially: start at 0, then merge each occurrence.

### Edge Classification

A "component" of an error instruction (the targets before, between, or after `^` separators) is an **edge** if it contains ≤2 detector targets. Components with >2 detectors are undecomposed hyperedges — skip them when building edge matrices, but still include the full hyperedge in the check_matrix. The first time an edge is registered, its observable set is recorded. If the same edge (same detector set) appears again, the observable set is overwritten with the latest value.

### Hyperedge-to-Edge Decomposition

For each hyperedge, record the set of edge IDs from its decomposed components. This mapping is stored only the first time the hyperedge is encountered; later occurrences do not update it.

## MWPMDecoder

Minimum-weight perfect matching decoder for quantum error correcting codes.

### Allowed Dependencies

You may use: `stim`, `numpy`, `scipy`, `networkx`, and the Python standard library. You must **not** use `pymatching`, `beliefmatching`, or `stimbposd`.

### Graph Construction

Build a weighted detector graph from the DEM:

1. For each `error(p)` instruction, split targets into components by `^` separator
2. For each component with 1 detector: add edge from that detector to a **virtual boundary node** with weight `log((1-p)/p)` and the component's observable set
3. For each component with 2 detectors: add edge between them with weight `log((1-p)/p)` and the component's observable set
4. Skip components with 0 or >2 detectors
5. If multiple edges connect the same node pair, keep the one with minimum weight (along with its observable set)

### Decoding Algorithm

Given a binary syndrome array (length `num_detectors`):

1. Find triggered detectors (indices where syndrome = 1)
2. If no triggered detectors, return all-zeros prediction
3. If odd number of triggered detectors, add the virtual boundary node
4. Compute shortest-path distances between all pairs of triggered nodes in the detector graph, tracking the cumulative observable XOR along each shortest path
5. Build a complete graph on triggered nodes with edge weights = shortest-path distances
6. Find minimum-weight perfect matching (e.g., using `networkx.min_weight_matching`)
7. For each matched pair, XOR their shortest-path observable contributions
8. Return the predicted observable flips as a binary array of length `num_observables`

### Batch Decoding

`decode_batch(shots)` takes a 2D array of shape `(num_shots, num_detectors)` and returns predictions of shape `(num_shots, num_observables)`, applying `decode` to each row.
