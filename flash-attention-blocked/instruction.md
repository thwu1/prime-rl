`/app/` contains a partially built system for computing scaled dot-product attention through a C shared library called via Python ctypes:

- `/app/src/blocked_attention.c` — C implementation (non-causal variants only)
- `/app/src/blocked_attention.h` — C header
- `/app/Makefile` — build configuration
- `/app/attention.py` — Python ctypes wrapper (non-causal variants only)
- `/app/flash_attention.py` — Python module stub
- `/app/reference.py` — naive O(N²) Python reference implementations for correctness comparison

Make `/app/flash_attention.py` expose four functions, all backed by the compiled C shared library `libattention.so`:

- `flash_attention_forward(Q, K, V, block_size)` → `(O, L)`
- `flash_attention_causal_forward(Q, K, V, block_size)` → `(O, L)`
- `flash_attention_backward(Q, K, V, O, dO, L, block_size)` → `(dQ, dK, dV)`
- `flash_attention_causal_backward(Q, K, V, O, dO, L, block_size)` → `(dQ, dK, dV)`

These compute scaled dot-product attention: `O = softmax(Q K^T / sqrt(d)) V` where Q, K, V are 2D float64 NumPy arrays of shape `(N, d)`. L is a 1D float64 array of length N containing per-row auxiliary values from the forward pass that the backward pass requires as input. Backward functions compute gradients dQ, dK, dV given upstream gradient dO. Causal variants restrict each position to attend only to earlier positions (j <= i).

**Constraints:**
- No intermediate array of size N×N or larger may be allocated at any point (in C or Python)
- Forward outputs must match `/app/reference.py` within 1e-10 absolute tolerance; backward gradients within 1e-8
- Must handle: N not divisible by block_size, block_size=1, block_size > N, N=1
- All four functions must execute through the compiled C shared library via ctypes
- All computation in float64