A partially implemented CAPRI protein-protein docking quality scorer is at `/app/capri_scorer.cpp` with `/app/Makefile`. The compiled binary evaluates docking models against a reference structure, computing standard CAPRI metrics. The implementation contains multiple bugs producing incorrect results and is missing required functionality. Fix all bugs and complete the implementation.

**Usage:** `./capri_scorer <reference.pdb> <model.pdb> <receptor_chain> <ligand_chains> [contact_cutoff]`

Default contact cutoff is 5.0 Angstroms. `ligand_chains` is a string of chain IDs (e.g., "B" or "BC").

**Multi-model support:** The model PDB file may contain multiple conformations delimited by MODEL/ENDMDL records. When multiple models are present, score each independently against the reference and report only the best (highest DockQ). Output a `model=N` line using the PDB MODEL serial number before the metrics. For single-model files or files without MODEL/ENDMDL records, omit the `model=` line.

**Required output** (stdout, exact format, 4 decimal places for floats):
```
model=2
fnat=0.8000
fnonnat=0.1500
irmsd=1.2345
lrmsd=3.4567
dockq=0.6789
quality=Medium
```

**Metric definitions:**

*f-nat*: Fraction of reference inter-chain contacts preserved in the model. A residue-level contact `(chain1, resSeq1, chain2, resSeq2)` exists when any pair of heavy (non-hydrogen) atoms from those residues on different chains is within cutoff. Hydrogen atoms include names starting with `H` and old-style numbered names where the first character is a digit and the second is `H` (e.g., `1HB`, `2HG2`). `fnat = |ref ∩ model| / |ref|`. If `|ref| = 0`, fnat = 0.0.

*f-nonnat*: Fraction of non-native contacts. `fnonnat = |model - ref| / |model|`. If `|model| = 0`, fnonnat = 0.0.

*i-RMSD*: Interface RMSD. Interface residues: all residues in any reference inter-chain contact. Extract backbone atoms (N, CA, C, O). Kabsch-superpose model onto reference via SVD. Rotation must be proper (det = +1). Report RMSD after superposition.

*l-RMSD*: Ligand RMSD. Extract all backbone atoms. Center by receptor-chain backbone centroid. Kabsch-superpose using receptor backbone only. Report RMSD of ligand backbone atoms after applying the rotation.

*DockQ*: `DockQ = fnat/3 + (1/(1+(irmsd/1.5)^2))/3 + (1/(1+(lrmsd/8.5)^2))/3`

*Quality* (standard CAPRI protein-protein, evaluated in order):
- **High**: fnat >= 0.5 AND (lrmsd <= 1.0 OR irmsd <= 1.0)
- **Medium**: fnat >= 0.3 AND (lrmsd <= 5.0 OR irmsd <= 2.0)
- **Acceptable**: fnat >= 0.1 AND (lrmsd <= 10.0 OR irmsd <= 4.0)
- **Incorrect**: otherwise

Sample data: `/app/data/reference.pdb`, `/app/data/model.pdb`. Eigen3 is at `/usr/include/eigen3`.
