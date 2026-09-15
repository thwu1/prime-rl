A spectral graph wavelet analysis pipeline at `/app/` produces incorrect results. The pipeline combines a C shared library for Chebyshev polynomial operations (source at `/app/sgwt_native/`, built via `/app/Makefile`) with Python modules (`/app/sgwt_lib/`) for spectral graph operations. One algorithmic component is entirely unimplemented. Diagnose and fix the pipeline so that `cd /app && make && python3 /app/run_sgwt.py` generates a numerically correct `/app/results.json`.

**Input:** `/app/graph_spec.json` (do not modify)

**Reference documentation:** `/app/docs/`

**Required output schema (`/app/results.json`):**

| Key | Type |
|-----|------|
| `eigenvalues` | sorted array of floats |
| `log_scales` | array of floats |
| `meyer_analysis_exact` | 2D array (N x Nf) |
| `meyer_frame_bounds` | [A, B] |
| `mexicanhat_analysis_exact` | 2D array (N x Nf) |
| `chebyshev_meyer_analysis` | 2D array (N x Nf) |
| `chebyshev_max_error` | float |
| `meyer_reconstruction_error` | float |
| `jackson_chebyshev_coefficients` | array of floats |

**Constraints:**
- Must not import or depend on `pygsp`, `PyGSP`, `gspbox`, or `sgwt_toolbox`
- Only `numpy` and `scipy` permitted as numerical dependencies
- Do not modify `/app/graph_spec.json`
- The C shared library must compile via `make` and be loaded for Chebyshev filtering

**Verification tolerances:**
- Eigenvalues, exact analyses, frame bounds, reconstruction error, Jackson coefficients: `atol <= 1e-8`
- Chebyshev-approximate analysis: `atol <= 1e-6`
- Meyer tight-frame property: `|A - B| < 0.01`, both near 1.0
- Meyer reconstruction error below `1e-6`
