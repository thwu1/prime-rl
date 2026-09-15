The signal processing project at `/app/` requires a from-scratch implementation of elliptic (Cauer) analog lowpass filter design, plus Bode magnitude plots generated via the project's `filterspec` CLI toolchain and `gnuplot`.

## Implementation

Complete `/app/elliptic_filter.py` providing these six functions (see the stub for full signatures and docstrings):

- `complete_elliptic_K(k)` — Complete elliptic integral K(k), modulus k in (0,1). Relative error < 1e-10.
- `cd_jacobi(u, k)` — Jacobian elliptic cd(u,k). Must satisfy cd(0,k)=1, cd(K,k)=0, even symmetry cd(-u,k)=cd(u,k), period 4K. Absolute error < 1e-10.
- `sn_jacobi(u, k)` — Jacobian elliptic sn(u,k). Must satisfy sn(0,k)=0, sn(K,k)=1, odd symmetry sn(-u,k)=-sn(u,k). Absolute error < 1e-10. Must be consistent with cd: sn(u,k) = cd(u-K(k),k) to within 1e-9.
- `cd_inverse(y, k)` — Inverse cd. Round-trip error < 1e-8. cd_inverse(1,k)=0, cd_inverse(0,k)=K(k).
- `sn_inverse(y, k)` — Inverse sn. Round-trip error < 1e-8. sn_inverse(0,k)=0, sn_inverse(1,k)=K(k).
- `elliptic_filter_design(N, rp, rs)` → (zeros, poles, gain) as ZPK arrays:
  - All poles must have negative real parts (open left half-plane)
  - All zeros must be purely imaginary, arranged in conjugate pairs
  - Complex poles must also form conjugate pairs
  - Odd N: N poles (one real), N-1 zeros, DC gain |H(0)| = 1.0
  - Even N: N poles, N zeros (all in conjugate pairs), DC gain |H(0)| = 10^(-rp/20)
  - Passband: |H(jw)| in [10^(-rp/20), 1.0] for w in [0, 1]
  - Stopband: |H(jw)| ≤ 10^(-rs/20) beyond the stopband edge
  - Pole/zero absolute error < 1e-4, gain relative error < 1e-3 vs. reference

**Forbidden imports** in `elliptic_filter.py`: `scipy`, `mpmath`, or any library providing elliptic functions, integrals, or filter design routines. Only `numpy` and the Python standard library are allowed.

Reference configurations in `/app/reference_data/`: order 3 (rp=3.0, rs=30), order 4 (rp=0.5, rs=60), order 5 (rp=1.0, rs=40), order 7 (rp=0.1, rs=80).

## Bode Plot Generation

After implementation, generate Bode magnitude plots for all four reference configurations. The project includes `/app/tools/filterspec.py`, a multi-subcommand CLI tool for analyzing reference data (`analyze`), exporting ZPK data (`export-zpk`), generating gnuplot scripts with frequency response data (`bode-script`), and running a full export-to-plot pipeline (`pipeline`). Run `python3 tools/filterspec.py --help` from `/app/` for usage details. `gnuplot` is pre-installed in the environment.

Each reference configuration must produce a valid SVG file at `/app/output/<config_basename>.svg`, where `<config_basename>` matches the reference JSON filename without extension (e.g., `order5_rp1.0_rs40.svg` for `order5_rp1.0_rs40.json`). Each SVG must contain valid gnuplot-generated markup exceeding 1000 bytes.

## Validation

Run `make full-pipeline` from `/app/` to execute the complete validation chain: forbidden-import scan (`check-deps`), mathematical and filter correctness against reference data (`validate`), and Bode plot generation via `filterspec` + `gnuplot` (`bode`).