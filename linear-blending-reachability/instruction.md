A blending controller operates on a sequence of concentrations stored in `/app/input.txt`. A single blending operation selects any contiguous window of exactly `k` consecutive elements and runs for a duration `t ∈ [0, 1]`. During blending, each element `a_j` in the selected window transitions linearly toward the window's arithmetic mean `μ`: at time `t`, the element's value becomes `a_j·(1 − t) + μ·t`. Elements outside the selected window remain unchanged. At most one blending operation may be applied.

**Input** (`/app/input.txt`):
- Line 1: integers `n`, `m`, `k` — sequence length, target range upper bound, window size
- Line 2: `n` space-separated integers — the concentration sequence

**Task**: For each integer target `x` from `1` to `m`, compute the minimum blending time at which `x` appears anywhere in the sequence. If `x` already exists in the original sequence, output `0`. If no single blending operation can produce `x`, output `-1`.

**Output** (`/app/output.txt`): exactly `m` lines. Line `x` contains the answer for target value `x`. Floating-point values must have absolute error ≤ 10⁻⁹. Output `-1` (no decimal point) for unreachable targets.