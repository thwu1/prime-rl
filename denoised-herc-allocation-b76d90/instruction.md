A draft portfolio allocation tool exists at `/app/denoised_herc_draft.py`. It runs without errors but produces incorrect allocations on several test scenarios. Research notes describing the intended methodology are at `/app/docs/notes.md`. A sample dataset is at `/app/data/sample_returns.csv`.

Diagnose the defects in the draft, then deliver a corrected and complete implementation at `/app/denoised_herc.py` that satisfies all requirements below.

**CLI:**
```
python3 /app/denoised_herc.py --input <csv> --output <json> \
  [--risk-measure cvar|variance|std] [--linkage ward|single|complete|average] \
  [--cvar-alpha 0.05] [--denoise] [--kde-bwidth 0.25]
```

`--input` and `--output` are required paths. `--denoise` is a boolean flag (store_true).

**Input CSV:** Date index column, then one column per asset containing daily log returns.

**Output JSON** (written to `--output` path):
```json
{"weights": {"TICKER": float, ...}, "n_clusters": int, "denoised": bool}
```

The module must also export `denoise_covariance`, `herc_allocate`, and `compute_cvar` as importable functions with APIs consistent with the test suite.

**Constraints:**
- All weights non-negative, sum to 1.0 (tolerance 1e-8), every input asset present with nonzero weight.
- `n_clusters`: positive integer <= number of assets, determined automatically (deterministic, seed 42).
- `denoised`: `true` when `--denoise` is passed, `false` otherwise.
- Must handle portfolios from 2 to 30+ assets.
- For block-structured return data, within-block weight dispersion must be lower than total weight dispersion.
- Different risk measures on the same data must yield distinct weight vectors.
- When denoising is active, the covariance used for allocation must differ measurably from the raw sample covariance.
- After denoising, noise eigenvalues of the correlation matrix must have reduced dispersion relative to the raw matrix.
- For clearly separated cluster structures in the data, detected cluster count must reflect the true number of groups.
- Lower-risk asset groups must receive greater total allocation weight than higher-risk groups.
