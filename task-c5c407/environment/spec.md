# RNA 3D Structure Assessment — Metrics Specification

## 1. Scope

Assessment of predicted RNA 3D structures against an experimental reference structure. Input: PDB coordinate files. Output: per-model quality metrics, pairwise structural distances, and a quality evaluation report.

## 2. Data Handling

### 2.1 PDB Parsing

Extract ATOM records from PDB files. Each ATOM record encodes atom name (columns 13–16), residue name (columns 18–20), residue sequence number (columns 23–26), and x/y/z coordinates (columns 31–54). Standard RNA nucleotides are A, G, C, U.

### 2.2 Modified Nucleotides

RNA PDB files frequently contain post-transcriptionally modified nucleotides with non-standard three-letter residue codes. These must be mapped to their parent standard bases before analysis. Common RNA modifications include methylated adenosines (e.g. 1-methyladenosine), pseudouridines, methylated guanosines, methylated cytidines, and various other post-transcriptional modifications. Inspect the data files to identify which non-standard residue codes are present and determine the correct parent base for each. Only atoms belonging to residues that can be mapped to standard bases (A, G, C, U) should be included; all others must be discarded.

### 2.3 Atom Naming

PDB files may use legacy atom naming conventions (asterisk notation, e.g. C1\*, O2\*) alongside the current IUPAC/PDB standard (prime notation, e.g. C1', O2'). Atom names must be normalized to a consistent convention before matching between structures. All sugar atom positions (C1–C5, O2–O5) may appear in either convention and must be handled.

### 2.4 Atom Matching

Atoms are matched between two structures by the tuple (residue_number, normalized_atom_name). Only atoms present in both structures of a comparison pair contribute to metrics.

## 3. Metrics

### 3.1 RMSD (Root Mean Square Deviation)

All-atom RMSD after optimal rigid-body superposition of matched atoms:

    RMSD = sqrt( (1/N) * sum_i || q_i - (R * p_i + t) ||^2 )

where {p_i} and {q_i} are matched atom coordinate sets from the two structures being compared, R is the optimal rotation matrix, t is the optimal translation vector, and N is the number of matched atoms. The superposition must minimize RMSD over all possible rotations and translations (global minimum, not a local approximation).

### 3.2 P-value (Statistical Significance)

Gumbel extreme-value distribution p-value:

    mu = 3.38 * L^0.44
    beta = 0.49 * L^0.24
    p = exp( -exp( -(RMSD - mu) / beta ) )

where L is the number of residues in the reference sequence.

### 3.3 Per-residue RMSD

For each reference residue (in ascending residue number order), compute the RMSD of atoms belonging to that residue, using the rotation and translation determined from the full matched atom set superposition. Report 0.0 for residues with no matched atoms.

### 3.4 Matched Atom Count

Number of (residue_number, normalized_atom_name) tuples present in both structures.

## 4. Output

### 4.1 results.json

Per-model assessment against the reference:

```json
{
  "assessments": [
    {
      "model": "<name>",
      "rmsd": 1.234,
      "p_value": 0.001,
      "num_matched_atoms": 250,
      "per_residue_rmsd": [0.5, 1.2, ...]
    }
  ],
  "ranking": ["<name>", ...]
}
```

- `assessments`: one entry per model, sorted alphabetically by model name
- `model`: PDB filename without the `.pdb` extension
- `ranking`: model names in ascending RMSD order (best prediction first)

### 4.2 pairwise_rmsd.json

All-vs-all structural comparison across all six structures (five models + reference):

```json
{
  "structures": ["model_01", "model_02", "model_03", "model_04", "model_05", "reference"],
  "matrix": [[0.0, 5.1, ...], ...]
}
```

- `structures`: all six structure names, sorted alphabetically
- `matrix[i][j]`: RMSD between `structures[i]` and `structures[j]` after optimal superposition using atoms present in both
- Diagonal entries are 0.0; matrix is symmetric

### 4.3 quality_report.json

Evaluation report analyzing the computed metrics:

```json
{
  "best_model": "<model with lowest RMSD>",
  "worst_model": "<model with highest RMSD>",
  "structurally_similar_pairs": [["model_XX", "model_YY"], ...],
  "coverage_analysis": {
    "full_coverage_models": ["model_XX", ...],
    "partial_coverage_models": ["model_XX", ...]
  }
}
```

- `best_model`: the model name with the lowest RMSD to the reference (first in ranking)
- `worst_model`: the model name with the highest RMSD to the reference (last in ranking)
- `structurally_similar_pairs`: pairs of models (excluding reference) whose pairwise RMSD after optimal superposition is below 5.0 Angstroms. Each pair is a two-element list sorted alphabetically. The list of pairs is sorted lexicographically.
- `full_coverage_models`: models whose `num_matched_atoms` equals the maximum `num_matched_atoms` across all five models, sorted alphabetically
- `partial_coverage_models`: all other models, sorted alphabetically
