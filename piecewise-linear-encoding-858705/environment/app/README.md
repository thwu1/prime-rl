# PLE — Piecewise-Linear Encoding

A numerical feature encoding library for tabular deep learning.

Transforms each numerical feature into a vector of per-bin components
based on computed bin edges. Supports quantile-based and decision-tree-based
bin computation strategies.

## Modules

- `ple/bins.py` — Bin edge computation (`compute_bins`)
- `ple/encoder.py` — Encoding logic (`PiecewiseLinearEncoder`)
- `ple_encode.py` — Command-line interface

## Quick Start

```python
from ple.encoder import compute_bins, PiecewiseLinearEncoder

bins = compute_bins(X, n_bins=48)
enc = PiecewiseLinearEncoder(bins)
structured = enc.encode_structured(X)  # (batch, features, max_bins)
flat = enc.encode_flat(X)              # (batch, total_bins)
```

## CLI

```bash
python3 ple_encode.py --input data.npy --n-bins 48 --format structured --output out.npy
```
