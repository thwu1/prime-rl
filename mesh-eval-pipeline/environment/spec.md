# Geometric Evaluation Metrics — Specification

## Overview

This pipeline evaluates geometric similarity between pairs of 3D triangle meshes
stored as binary STL files. For each pair it computes six metrics, a composite
similarity score, and a validity classification. Results are written as JSON.

## Command-Line Interface

```
python3 /app/evaluate.py \
    --pairs /app/models/pairs.json \
    --samples 10000 \
    --voxel-res 32 \
    --seed 42 \
    --output /app/results.json
```

| Argument      | Type | Description                                         |
|---------------|------|-----------------------------------------------------|
| `--pairs`     | str  | Path to JSON file listing reference/candidate pairs  |
| `--samples`   | int  | Number of points to sample from each mesh surface    |
| `--voxel-res` | int  | Number of voxels per axis for IoU grid               |
| `--seed`      | int  | Random seed for reproducible surface sampling        |
| `--output`    | str  | Path to write JSON results                           |

## Input Format

`pairs.json`:
```json
{
  "pairs": [
    {"id": "pair_1", "reference": "ref_box.stl", "candidate": "cand_box_match.stl"}
  ]
}
```

Reference STL files are in `<pairs_dir>/references/`.
Candidate STL files are in `<pairs_dir>/candidates/`.

---

## 1. Chamfer Distance (CD)

Given reference point set **P** and candidate point set **Q**, each containing
*N* points sampled uniformly from their respective mesh surfaces:

```
CD = (1/2) · [ (1/|P|) Σ_{p∈P} min_{q∈Q} ‖p − q‖²
             + (1/|Q|) Σ_{q∈Q} min_{p∈P} ‖q − p‖² ]
```

**Uniform surface sampling** requires area-proportional triangle selection:
the probability of sampling from triangle *i* equals `area(i) / total_area`.

**Units**: mm² (mean of **squared** Euclidean nearest-neighbor distances).

## 2. Hausdorff Distance (HD)

```
HD = max( max_{p∈P} min_{q∈Q} ‖p − q‖ ,
          max_{q∈Q} min_{p∈P} ‖q − p‖ )
```

HD is the **bidirectional** maximum of minimum point-to-set distances — both
the forward (P→Q) and backward (Q→P) directions must be evaluated.

**Units**: mm (Euclidean distance, **not** squared).

## 3. 95th-Percentile Hausdorff Distance (HD95)

```
HD95 = max( P95({min_{q∈Q} ‖p − q‖ : p ∈ P}) ,
            P95({min_{p∈P} ‖q − p‖ : q ∈ Q}) )
```

A robust variant of Hausdorff Distance that replaces the maximum with the
95th percentile in each direction. This reduces sensitivity to outlier points
caused by tessellation artifacts or sampling noise.

Like HD, it must be computed **bidirectionally** — evaluate the 95th percentile
of nearest-neighbor distances in both directions and return the larger value.

**Units**: mm (Euclidean distance, **not** squared).

**Invariant**: HD95 ≤ HD for any point sets P, Q.

## 4. Voxelized Intersection over Union (IoU)

1. Compute the axis-aligned bounding box encompassing **both** meshes.
2. Pad bounds by **5%** of each axis extent.
3. Create an *R × R × R* regular grid within the padded bounds (`indexing='ij'`).
4. Determine solid containment of each grid point within **each** mesh
   independently (ray-based containment testing).
5. `IoU = |inside_A ∩ inside_B| / |inside_A ∪ inside_B|`

If the union count is zero, return `IoU = 0.0`.

## 5. Surface Deviation Profile

Compute the bidirectional surface deviation histogram:

1. Compute forward nearest-neighbor distances: `d_fwd_i = min_{q∈Q} ‖p_i − q‖` for each `p ∈ P`.
2. Compute backward nearest-neighbor distances: `d_bwd_j = min_{p∈P} ‖q_j − p‖` for each `q ∈ Q`.
3. Concatenate all distances into a single array `D = [d_fwd_1, …, d_fwd_N, d_bwd_1, …, d_bwd_N]`.
4. Determine `d_max = max(D)`.
5. Create `n_bins` (default: 10) equal-width bins spanning `[0, d_max]`.
6. Compute the histogram of `D` over these bins.
7. Normalize the histogram so the bin values sum to 1.0.
8. Return as a list of `n_bins` floats.

If `d_max < 1e-12` (all distances effectively zero), return `[1.0, 0.0, …, 0.0]`.

**Units**: dimensionless (normalized frequency).

## 6. Mesh Validity

A mesh is **invalid** if any of:
- Is empty (no faces)
- Not watertight (has boundary edges / open faces)
- Volume ≤ 0
- Contains any face with area < 1e-10

When **either** mesh in a pair is invalid:
- `chamfer_distance`: `null` (JSON null)
- `hausdorff_distance`: `null` (JSON null)
- `hausdorff_95`: `null` (JSON null)
- `iou`: `0.0`
- `deviation_profile`: `null` (JSON null)
- `similarity_score`: `null` (JSON null)

## 7. Composite Geometric Similarity Score

A single normalized score in [0, 1] combining all individual metrics, where
higher values indicate greater geometric similarity between the reference and
candidate meshes.

### Distance-to-similarity normalization

Unbounded distance metrics (CD, HD, HD95) are mapped to [0, 1] using:

```
sim(d, k) = k / (d + k)
```

This function is monotonically **decreasing** in *d*: larger distances produce
lower similarity. Boundary values: `sim(0, k) = 1` (identical surfaces) and
`sim(∞, k) → 0` (infinitely distant surfaces).

Scale constants (chosen to reflect typical metric magnitudes in mm/mm² units):
- Chamfer Distance: k = 100
- Hausdorff Distance: k = 50
- 95th-Percentile Hausdorff Distance: k = 50

### Bounded metrics

- **IoU**: used directly (already a similarity measure in [0, 1]).
- **Profile concentration**: sum of the first 3 bins of the deviation profile
  (captures the fraction of surface area with small deviations).

### Weighted combination

```
score = 0.30·sim(CD, 100) + 0.15·sim(HD, 50) + 0.10·sim(HD95, 50)
      + 0.30·IoU + 0.15·concentration
```

### Properties

- `score ∈ [0, 1]`
- Monotonically non-decreasing with geometric similarity
- `null` for any pair where any component metric is null, or the deviation
  profile is unavailable or has fewer than 3 bins

### Invariant

For any two pairs (A, B) where A is more geometrically similar than B across
all individual metrics, `score(A) ≥ score(B)`.

## Output Format

Write a JSON file at `--output`:

```json
{
  "metrics": [
    {
      "pair_id": "pair_1",
      "reference": "ref_box.stl",
      "candidate": "cand_box_match.stl",
      "chamfer_distance": 0.0312,
      "hausdorff_distance": 0.876,
      "hausdorff_95": 0.654,
      "iou": 0.973,
      "deviation_profile": [0.85, 0.10, 0.03, 0.02, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
      "similarity_score": 0.962,
      "is_valid_ref": true,
      "is_valid_cand": true
    }
  ]
}
```

All numeric values must be JSON numbers (not strings).
Invalid metrics must be JSON `null` (not NaN, not `"null"`).
The `metrics` array must contain one entry per pair in the input, in the same order.
