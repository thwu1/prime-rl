The file `/app/nf4_published.json` contains the 16 codebook values of the NF4 (NormalFloat 4-bit) quantization format used in QLoRA model compression. These values define a 4-bit data type optimized for quantizing normally-distributed neural network weights.

Your task is to reverse-engineer the exact mathematical procedure that produces this codebook, identify its key construction parameter, and extend the construction to produce NF6 and NF8 codebooks at higher bit widths.

## Outputs

Write all output files to `/app/results/`:

- **`alpha.txt`** — The key construction parameter as an exact irreducible fraction (e.g. `3/4`)
- **`construction.py`** — A standalone Python module exporting `construct_nfn(n_bits: int, alpha: float) -> list[float]` that returns the sorted NFn codebook for any bit width n >= 2. The function must produce correct results for arbitrary values of the construction parameter, not just the one discovered from NF4.
- **`nf4_reproduced.json`** — JSON array of 16 floats: NF4 values reproduced by your construction (must match published values within 1e-6)
- **`nf6_values.json`** — JSON array of 64 floats: the NF6 codebook produced by your construction
- **`nf8_values.json`** — JSON array of 256 floats: the NF8 codebook produced by your construction
- **`quantization_errors.json`** — JSON object with keys `nf4`, `nf6`, `nf8`, `uniform4`, `uniform6`, `uniform8`, each mapping to the mean squared quantization error (MSE) when quantizing `/app/weights.json` using block-wise absmax quantization (block size 64). Uniform n-bit baselines use `2^n` evenly spaced levels from -1 to 1 inclusive.