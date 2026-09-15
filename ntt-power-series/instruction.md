A hybrid C/Python formal power series (FPS) library at `/app/` is broken across multiple layers.

**Architecture:**
- `/app/ntt.c`, `/app/ntt.h` — C implementation of Number Theoretic Transform and polynomial multiplication
- `/app/Makefile` — builds `libntt.so` shared library from the C source
- `/app/ntt_binding.py` — Python ctypes FFI wrapper that loads `libntt.so` and exposes `multiply()`
- `/app/mod_arith.py` — pure Python modular arithmetic utilities (believed correct)
- `/app/fps.py` — higher-level FPS operations (`poly_inv`, `poly_deriv`, `poly_integ`, `poly_ln`, `poly_sqrt`, `poly_exp`, `poly_pow`) built on top of the C multiply backend

**Known state:**
- `make` in `/app/` does not produce a usable shared library
- Even after building, `multiply()` called through the Python bindings returns incorrect results
- `poly_inv()` computes wrong coefficients (independent of multiply issues)
- `poly_exp()` and `poly_pow()` raise `NotImplementedError`

Fix all issues across the build system, C code, ctypes bindings, and Python FPS layer. All polynomial arithmetic is in Z/998244353Z.

`poly_exp(f, n)`: First n coefficients of exp(f(x)) mod x^n. Requires f(0) = 0.

`poly_pow(f, k, n)`: First n coefficients of f(x)^k mod x^n. Requires f(0) = 1, k >= 0.

The corrected library must satisfy these identities:
- `multiply(a, b)` agrees with naive O(n^2) convolution
- `poly_inv(f, n) * f ≡ 1 (mod x^n)`
- `poly_exp(poly_ln(f, n), n) ≡ f (mod x^n)` when f(0) = 1
- `poly_sqrt(f, n)^2 ≡ f (mod x^n)` when f(0) = 1
- `poly_pow(f, k, n)` matches k-fold multiplication for small k