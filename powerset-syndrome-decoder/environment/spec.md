# Minimum-Weight Syndrome Decoder — Algorithm Specification

## 1. Problem Statement

Given a **Detector Error Model (DEM)** describing a set of possible errors with their probabilities, detector activations, and observable effects, and an observed **syndrome** (the set of detectors that fired), find the **minimum-weight error set** whose combined detector signature matches the syndrome via XOR.

## 2. DEM Format

A DEM is a text file with one error mechanism per line:

```
error(<probability>) <target1> <target2> ...
```

Where:
- `<probability>` is a float in (0, 1) — the independent probability of this error occurring
- Each `<target>` is either `D<n>` (detector index) or `L<n>` (logical observable index)
- Lines starting with `#` are comments; blank lines are ignored
- Errors with no detector targets should be ignored (they cannot resolve any syndrome)

The number of detectors and observables are inferred from the maximum indices seen.

**Example:**
```
error(0.10) D0 D1 L0
error(0.05) D1 D2
error(0.08) D2 D3 L1
```

This defines 3 errors over 4 detectors (D0–D3) and 2 observables (L0–L1).

## 3. Likelihood Cost

Each error `e` with probability `p` has a **likelihood cost**:

```
w(e) = −ln(p / (1 − p))
```

For `p < 0.5`, this cost is positive. Finding the minimum-weight error set is equivalent to maximum-likelihood decoding.

## 4. Syndrome Matching

For an error `e`, let `D(e)` denote its set of detector indices. For a set of errors `F`, the **combined detector signature** is the symmetric difference (XOR) of individual signatures:

```
D(F) = D(e₁) ⊕ D(e₂) ⊕ ... ⊕ D(eₖ)
```

A set `F` **matches** syndrome `S` if `D(F) = S`.

The **residual syndrome** after selecting errors `F` from initial syndrome `S` is:

```
R(F) = S ⊕ D(F)
```

When `R(F) = ∅`, the syndrome is fully resolved.

## 5. Observable Prediction

Each error `e` also has a set of observable indices `O(e)`. The predicted flipped observables are:

```
O(F) = O(e₁) ⊕ O(e₂) ⊕ ... ⊕ O(eₖ)
```

## 6. Power-Set Graph

The decoding problem is formulated as a **shortest-path search** on a directed acyclic graph over the power set of errors:

- **Nodes**: subsets `F ⊆ E` of the error set
- **Edges**: `F → F ∪ {e}` for each error `e ∉ F`, with weight `w(e)`
- **Start**: empty set `∅`
- **Goals**: all `F` where `R(F) = ∅` (residual is empty)

The minimum-cost path from start to any goal gives the minimum-weight error set.

## 7. A* Search Algorithm

Use A* search with a min-heap priority queue ordered by `f = g + h`, where:
- `g` = total cost of errors in the current set (sum of `w(e)` for `e ∈ F`)
- `h` = admissible heuristic estimate of remaining cost

### Algorithm outline:

1. Initialize priority queue with the start state: `g=0`, residual `R = S`, empty error chain
2. Pop the state with minimum `f` from the queue
3. If `R = ∅`, return the error chain as the solution
4. Expand: generate successors by adding errors (subject to canonical ordering, see §8)
5. For each successor, compute new `g`, new `R`, and heuristic `h`; push to queue
6. Repeat until solution found, queue empty, or limits exceeded

## 8. Canonical Ordering

Without constraints, each error set `F` of size `k` can be reached via `k!` different orderings, creating massive redundancy. **Canonical ordering** eliminates this:

> At each expansion step, identify the **minimum-index detector** in the current residual `R`. Only expand errors that are **incident to** this detector (i.e., errors whose detector set includes this detector).

This ensures each error set has exactly one canonical path from the start, collapsing factorial redundancy to a tree structure.

## 9. Admissible Heuristic

The heuristic estimates the minimum additional cost to resolve all remaining detectors. For each detector `d` in residual `R`, compute the **minimum cost-per-detector** among available errors:

```
det_cost(d, R, U) = min { w(e) / |D(e) ∩ R|  :  e ∈ E(d) \ U,  |D(e) ∩ R| > 0 }
```

Where:
- `E(d)` = set of errors incident to detector `d`
- `U` = set of errors already used in the current chain
- `|D(e) ∩ R|` = number of residual detectors this error would help resolve

The heuristic is:

```
h(R, U) = Σ_{d ∈ R} det_cost(d, R, U)
```

If `det_cost(d, R, U) = ∞` for any `d ∈ R` (no available error can resolve detector `d`), then `h = ∞` and this branch is infeasible.

**Why admissible**: Each error in the optimal completion contributes its full cost `w(e)` but resolves `|D(e) ∩ R|` detectors. The per-detector share `w(e) / |D(e) ∩ R|` summed across resolved detectors exactly equals `w(e)`. Since `det_cost` takes the *minimum* such ratio for each detector, the total `h` never exceeds the true optimal remaining cost.

## 10. Beam Search

Track the minimum residual size seen so far: `min_res`. **Prune** any state where:

```
|R| > min_res + beam_width
```

This prevents the search from exploring states where the residual has grown too far above the best seen. The `beam_width` parameter controls the tradeoff between accuracy and speed.

## 11. Priority Queue Limit

If the total number of states pushed to the priority queue exceeds `pq_limit`, **abort** the search and report `low_confidence = True`. This provides a hard bound on computational effort.

## 12. API Requirements

Implement the `SyndromeDecoder` class in `/app/decoder.py` with the following interface:

```python
class SyndromeDecoder:
    def __init__(self, dem_text: str, beam_width: int = 5, pq_limit: int = 200000):
        """
        Initialize the decoder with a DEM and search parameters.

        Args:
            dem_text: DEM in text format (see §2)
            beam_width: Maximum residual growth above minimum seen (see §10)
            pq_limit: Maximum priority queue pushes before aborting (see §11)
        """

    def decode(self, syndrome: list[int]) -> dict:
        """
        Decode a syndrome.

        Args:
            syndrome: List of activated detector indices.

        Returns:
            dict with keys:
                'errors': sorted list of error indices (0-based, matching DEM order)
                'observables': sorted list of flipped observable indices
                'cost': total likelihood cost of the predicted error set (float)
                'low_confidence': True if search was truncated by pq_limit
        """

    @property
    def num_errors(self) -> int:
        """Number of valid error mechanisms parsed from the DEM."""

    @property
    def num_detectors(self) -> int:
        """Number of detectors (max detector index + 1)."""

    @property
    def num_observables(self) -> int:
        """Number of observables (max observable index + 1)."""
```

### Behavioral requirements:

- Empty syndrome `[]` should return `errors=[], observables=[], cost=0.0, low_confidence=False`
- Error indices in the output correspond to the order errors appear in the DEM (0-based), counting only valid errors (those with `0 < p < 1` and at least one detector target)
- Costs must be computed using natural logarithm
- The decoder must find **optimal** (minimum-cost) solutions when `beam_width` and `pq_limit` are sufficiently large
- For infeasible syndromes, return `low_confidence=True` with `cost=inf`
