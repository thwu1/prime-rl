Implement a complete post-training weight quantization system based on the Optimal Brain Quantization (OBQ) framework in `/app/quantizer.py`. The algorithm uses second-order (Hessian) information from calibration data to compensate quantization errors across weight matrix columns, minimizing Hessian-weighted reconstruction error.

Mathematical specification: `/app/spec.md`. Pre-trained weight matrices and calibration data: `/app/data/`.

Implement all five functions in `/app/quantizer.py`:
- `uniform_quantize`: Symmetric and asymmetric uniform quantization with proper scale/zero-point computation and edge case handling
- `compute_hessian`: Hessian matrix H = 2X^TX/N from calibration data
- `obq_quantize`: Sequential column-wise quantization with Hessian-inverse error compensation; must support blocked column processing (block_size parameter) with within-block and cross-block updates
- `obq_quantize_actorder`: OBQ with activation-magnitude column reordering — columns with larger Hessian diagonal are quantized first, then results are un-permuted
- `mixed_precision_search`: Given pre-computed per-layer quantization errors for each bit-width option, find the optimal bit-width assignment across layers via dynamic programming under a total storage budget constraint

Do not change function signatures. Only numpy is available.