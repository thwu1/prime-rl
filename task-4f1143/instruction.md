An elliptic (Cauer) filter design and discretization pipeline is deployed at `/app/`:

- `/app/elliptic_core.c` and `/app/libelliptic.so` — C shared library for elliptic integral and Jacobian elliptic function computations via Landen transformations
- `/app/elliptic.py` — Python module that wraps the C library and provides routines for analog elliptic filter prototype design and digital IIR filter discretization

The pipeline has two categories of problems:

**Analog prototype bugs**: `elliptic.elliptic_filter(N, Rp, Rs)` should return `(zeros, poles, gain)` matching `scipy.signal.ellipap(N, Rp, Rs)` for orders 3–9, but multiple independent mathematical defects across the C and Python components produce incorrect output. The code compiles and runs without crashes. Diagnose the defects by tracing through the Landen transformation algorithms and comparing intermediate computations against known mathematical identities and `scipy` reference values. Fix all issues in `/app/elliptic_core.c` and `/app/elliptic.py`, then recompile the shared library.

**Missing discretization**: `elliptic.discretize_elliptic(N, Rp, Rs, fs, fc)` is stubbed out (`NotImplementedError`). Implement it to produce a digital IIR lowpass elliptic filter in second-order sections (SOS) format. The implementation must apply frequency pre-warping and the bilinear s-to-z transform to the analog prototype, then factor the resulting digital transfer function into cascaded biquad sections with properly computed and distributed gain. The output SOS array must produce a frequency response matching `scipy.signal.ellip(N, Rp, Rs, fc, fs=fs, output='sos')`.

## Constraints

- `/app/elliptic.py` may only import `cmath`, `math`, `numpy`, and `ctypes` (no `scipy`, `scipy.special`, or other elliptic function libraries)
- The existing exported API signatures must remain unchanged
- Tolerances: 1e-7 for analog pole/zero/gain; 0.01 dB for analog frequency response; 0.05 dB for digital frequency response