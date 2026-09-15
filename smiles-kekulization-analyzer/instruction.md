`/app/reference/` contains materials for understanding SMILES analysis semantics:

- `training_set.jsonl` — example SMILES with expected outputs (`tautomer_hash` omitted)
- `challenge_set.txt` — additional SMILES for investigation
- `notes.txt` — output conventions and format specifications
- `oracle.py` — RDKit-based reference tool (`echo "c1ccccc1" | python3 /app/reference/oracle.py`)

`python3-rdkit` is installed and available for interactive exploration (`from rdkit import Chem`).

**Deliverable**: `/app/smiles_analyze.py` — reads SMILES from stdin (one per line), writes JSONL to stdout. Must not import any cheminformatics library (rdkit, openbabel, pybel, partialsmiles, deepsmiles, or similar).

**Output schema** (one JSON object per input line):

```json
{"smiles":"…","valid":true,"error_type":null,"num_heavy_atoms":6,"implicit_hydrogens":[1,1,1,1,1,1],"molecular_formula":"C6H6","kekulizable":true,"tautomer_hash":"a1b2c3d4e5f6a7b8_0"}
```

For invalid SMILES: `valid` is `false`, `error_type` is one of `"syntax"`, `"valence"`, or `"kekulization"`, and all other fields are `null`.

For valid SMILES without aromatic atoms: `kekulizable` is `null`.

**Parsing scope**: organic subset atoms (B, C, N, O, P, S, F, Cl, Br, I), aromatic lowercase (b, c, n, o, p, s), bracket atoms `[isotope element chirality Hcount charge]`, ring closures (0–9 and `%nn`), branches, bonds (implicit, `-`, `=`, `#`, `:`), stereo bonds (`/`, `\` treated as single bonds), and dot disconnection.

**Success**: `bash /tests/test.sh` exits 0.
