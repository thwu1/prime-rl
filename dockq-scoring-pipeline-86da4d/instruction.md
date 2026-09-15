Implement a protein-protein docking quality assessment pipeline that integrates compiled MEGADOCK C tools with a scoring engine.

## Environment

- `/app/data/receptor.pdb` — receptor structure (chain B)
- `/app/data/ligand.pdb` — ligand structure (chain C)
- `/app/data/docking.out` — MEGADOCK-format docking output (10 poses)
- `/app/reference/decoygen.cpp` — MEGADOCK decoy generator C source
- `/app/reference/calcrg.cpp` — MEGADOCK center-of-geometry calculator C source
- `/app/reference/capri_criteria.txt` — CAPRI quality criteria definitions
- `/app/reference/dockq_paper.txt` — DockQ scoring metric definitions

## Required deliverables

### `/app/Makefile`

Must support targets `decoygen`, `calcrg`, `all`, and `clean`. `make all` builds both C binaries. `make clean` removes them. A `make clean && make all` cycle must succeed and produce working binaries.

### `/app/decoygen` (native ELF binary)

Compiled from the C source at `/app/reference/decoygen.cpp`. Generates a transformed ligand PDB from a MEGADOCK docking output file. The source's argument order differs from the required interface — adapt the code accordingly.

Required interface:
```
/app/decoygen <docking.out> <ligand.pdb> <pose_number> <output.pdb>
```

The coordinate transformation pipeline (centering, ZYZ Euler rotations, grid-wrapping, translation) must exactly reproduce the behavior of the original C implementation.

### `/app/calcrg` (native ELF binary)

Compiled from the C source at `/app/reference/calcrg.cpp`. Computes the transformed ligand center position for all poses in a docking output file.

```
/app/calcrg <docking.out> 0
```

Output: one CSV line per pose in the source's `%7.3f, %7.3f, %7.3f` format.

### `/app/dockq` (executable)

Protein-protein docking quality scorer.

```
/app/dockq <native.pdb> <model.pdb> --rec-chain <R> --lig-chain <L>
```

Output to stdout, one metric per line:
```
fnat <float>
lrms <float>
irms <float>
dockq <float>
capri <High|Medium|Acceptable|Incorrect>
```

All metrics must conform to the definitions in the provided reference materials. A self-comparison (native scored against itself) must yield `fnat 1.000000`, `lrms 0.000000`, `irms 0.000000`, `dockq 1.000000`, `capri High`.

### `/app/score_all.sh` (executable)

End-to-end pipeline: for each pose, generate the decoy, form a two-chain model complex with the receptor, score with `/app/dockq`, and obtain ligand center coordinates from `/app/calcrg`. Write a TSV table to stdout sorted by `dockq` descending:

```
pose	fnat	lrms	irms	dockq	capri	rg_x	rg_y	rg_z
```

Run as: `/app/score_all.sh /app/data/receptor.pdb /app/data/ligand.pdb /app/data/docking.out`
