PDB coordinate files in `/app/data/` contain `reference.pdb` (a 20-nucleotide single-chain RNA crystallographic reference) and five predicted model structures (`model_01.pdb` through `model_05.pdb`). A mathematical specification at `/app/spec.md` defines the required assessment metrics and output schemas. A stub pipeline exists at `/app/pipeline.py`.

Implement the complete assessment pipeline as `/app/pipeline.py` (executable via `python3 /app/pipeline.py`) that produces three output files:

1. `/app/results.json` — per-model quality metrics (RMSD after optimal superposition, Gumbel P-value, per-residue RMSD, matched atom count) with ranking
2. `/app/pairwise_rmsd.json` — all-vs-all structural distance matrix for all six structures
3. `/app/quality_report.json` — evaluation report classifying models by quality tier, identifying structurally similar pairs, and analyzing atom coverage

The PDB files contain RNA-specific data challenges that must be handled correctly for accurate results. The specification describes what to compute, not how — implementation decisions including algorithm selection, data normalization strategy, and edge case handling are yours to make.