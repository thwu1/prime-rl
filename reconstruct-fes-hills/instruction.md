The directory `/app/` contains PLUMED-format HILLS data files (`hills_1d.dat`, `hills_2d.dat`, `hills_2d_mv.dat`, `hills_1d_long.dat`) and reference FES outputs under `/app/ref/`. Inspect these files to understand the data formats and expected behavior.

Produce the following four files in `/app/`:

**`/app/sum_hills`** — Python executable. CLI:
```
python3 /app/sum_hills --hills <file> --grid-min=<v[,v]> --grid-max=<v[,v]> \
  --grid-bins=<n[,n]> --periodic=<true/false[,true/false]> --outfile <file>
```
Output format: 1D produces 3 whitespace-separated columns (`cv fes deriv`); 2D produces 5 columns (`cv1 cv2 fes dcv1 dcv2`) with a blank line separating each cv1 block. All numeric values must have at least 6 decimal places. Grid points are bin-centers (uniformly spaced).

**`/app/preprocess.awk`** — GNU AWK script. CLI:
```
gawk -v tmin=<f> -v tmax=<f> -f /app/preprocess.awk <hills_file>
```
Outputs a subset of the HILLS file containing only data rows whose time falls in `[tmin, tmax]` (inclusive on both boundaries). All `#!` metadata headers from the original file must appear in the output. When no data rows match, output contains only headers with no data rows.

**`/app/Makefile`** — Targets accepting command-line variables:
- `make -C /app fes HILLS=… GRID_MIN=… GRID_MAX=… GRID_BINS=… PERIODIC=… OUTFILE=…`
- `make -C /app converge HILLS=… GRID_MIN=… GRID_MAX=… GRID_BINS=… PERIODIC=… WINDOWS=… OUTFILE=…`
- `make -C /app clean`

**`/app/converge.py`** — Python executable invoked via `make converge`. Writes JSON to OUTFILE conforming to this schema:
```json
{"n_windows": <int>,
 "windows": [{"index": <int>, "time_end": <float>, "n_hills": <int>}, ...],
 "pairwise_metrics": [{"pair": [<i>,<j>], "fes_rmsd": <float>, "fes_max_diff": <float>}, ...],
 "final_rmsd": <float>}
```
`n_windows` equals the WINDOWS parameter. Each window is a cumulative slice from time 0 through its `time_end`. `n_hills` counts hills in that cumulative range and must increase monotonically across windows. `pairwise_metrics` contains N-1 entries comparing successive windows. `final_rmsd` equals the last entry's `fes_rmsd`. The convergence pipeline must fail (non-zero exit) if either `preprocess.awk` or `sum_hills` is removed from `/app/`.

**Success criteria:**
- FES values match independently-computed reference within 1e-4 absolute tolerance at arbitrary grid resolutions; derivatives within 1e-3
- Convergence JSON metrics are numerically accurate within 1e-3
- All tools handle both diagonal-covariance and multivariate (full covariance matrix) HILLS files, and both periodic and non-periodic collective variables
