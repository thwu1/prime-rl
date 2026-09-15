Build `/app/pdf_calc.py`, a CLI tool that computes the reduced pair distribution function G(r) for crystal structures.

**Interface:**

```
python3 /app/pdf_calc.py <structure_file> --rmax FLOAT --rstep FLOAT --qdamp FLOAT --output PATH
```

The tool must accept both PDFfit `.stru` and CIF `.cif` structure files. CIF files specify an asymmetric unit with space-group symmetry that must be expanded to obtain the full unit cell contents. Importing pre-built PDF calculator modules (`diffpy.srreal`, `PDFCalculator`, `DebyePDFCalculator`) is forbidden.

Input structures are at `/app/data/`: `Ni.stru` (4-atom FCC conventional cell, a=3.52 Å), `Ni_primitive.stru` (1-atom rhombohedral primitive cell), and `Ni.cif` (CIF with Fm-3m symmetry, same physical structure as the .stru files). All files contain displacement parameters.

**Output format:** Two whitespace-separated columns (r and G(r)). The r-grid spans `int(round(rmax/rstep))+1` uniformly spaced points from 0 to rmax inclusive. Lines beginning with `#` are ignored by the verifier.

The `qdamp` parameter controls instrumental Q-space resolution damping; when qdamp=0 no instrumental damping is applied.

**Acceptance criteria (all runs use rmax=10.0, rstep=0.01):**

- Output grid: exactly 1001 points with uniform rstep spacing
- G(r=0) must equal 0
- Ni.stru and Ni_primitive.stru (qdamp=0): maxNormDiff < 0.012 versus a known reference, where maxNormDiff = max(|a-b|) / max(|a|)
- Conventional-primitive consistency: maxNormDiff < 0.005
- Baseline: G(r) at r=0.50 Å (before the first peak) must be physically consistent with the crystal's number density, within 10% relative error
- First peak: maximum G(r) in [2.0, 3.0] Å must lie within 0.03 Å of ~2.489 Å, with amplitude > 20
- CIF input (qdamp=0): correct grid length, G(0) < 1e-6, first peak near 2.489 Å with amplitude > 15
- CIF-STRU consistency: maxNormDiff < 0.005
- Q-damping (qdamp=0.1 on Ni.stru): peaks in [7, 9] Å must be attenuated below 85% of their undamped amplitude; peaks in [2, 3] Å must retain > 90% of undamped amplitude
