The PLE (Piecewise-Linear Encoding) library at `/app/` encodes numerical features for tabular deep learning. The implementation has multiple interacting bugs across its bin computation, encoding, and CLI layers that cause incorrect results. The behavioral specification at `/app/SPEC.md` defines the correct behavior for every component.

Diagnose and fix all bugs so the library conforms to its specification. Additionally, create `/app/Makefile` to orchestrate the encoding pipeline.

**Required API** (preserve these signatures):

`compute_bins(X, n_bins=48, *, y=None, regression=None, tree_kwargs=None)` returns a list of 1-D edge arrays. `PiecewiseLinearEncoder(bins)` provides `encode_structured(X)`, `encode_flat(X)`, and properties `n_features`, `max_n_bins`, `total_n_bins`. CLI: `python3 /app/ple_encode.py --input P --n-bins N --format {structured,flat} --output P`.

**Makefile** at `/app/Makefile` with GNU Make targets accepting variables:

- `encode`: `INPUT`, `NBINS`, `FORMAT`, `OUTPUT` — encode input to output via the CLI.
- `batch`: `INPUT`, `NBINS`, `OUTDIR` — produce `$(OUTDIR)/structured.npy` and `$(OUTDIR)/flat.npy`.
- `report`: `INPUT`, `NBINS`, `OUTDIR` — run the batch pipeline, then write `$(OUTDIR)/report.json` containing keys `n_samples` (int), `n_features` (int), `n_bins_requested` (int matching `NBINS`), `structured_shape` (list of 3 ints), `flat_width` (int).
- `sweep`: `INPUT`, `OUTDIR` — encode `INPUT` at bin counts 4, 8, 16, 32, 64. For each count N, produce `$(OUTDIR)/bins_N/structured.npy` and `$(OUTDIR)/bins_N/flat.npy`. Write `$(OUTDIR)/sweep.json` mapping each count (string key) to `{"structured_shape": [3 ints], "flat_width": int}`.
- `clean`: `OUTDIR` — remove `$(OUTDIR)/*.npy`, `$(OUTDIR)/*.json`, and `$(OUTDIR)/bins_*/`.

All source files are under `/app/`. Do not modify the test suite.
