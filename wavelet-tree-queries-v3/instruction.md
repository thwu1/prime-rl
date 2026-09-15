A wavelet tree command-line tool is built from source at `/app/`. Running `make` in `/app/` produces the binary `/app/wt`. The codebase compiles without errors but produces incorrect results — some operations contain implementation defects while others are unimplemented stubs returning placeholder values. Diagnose all defects, implement all missing operations, and ensure every operation produces correct results.

The binary reads from stdin:

- Line 1: `n sigma` — sequence length and alphabet size (symbols in `[0, sigma)`)
- Line 2: `n` space-separated integers — the sequence
- Line 3: `q` — query count
- Next `q` lines: one query each

Each query produces exactly one integer on stdout (one per line).

**Operations:**

- `A i` — `s[i]`, or `-1` if `i ∉ [0, n)`
- `R c i` — occurrences of `c` in `s[0..i)` (exclusive); `0` for `c ∉ [0, sigma)` or `i ≤ 0`; clamp `i` to `n` if `i > n`
- `S c j` — 0-indexed position of the `j`-th occurrence of `c` (1-indexed `j`); `-1` if fewer than `j` exist, `c ∉ [0, sigma)`, or `j ≤ 0`
- `K l r k` — `k`-th smallest in `s[l..r)` (1-indexed `k`); `-1` for invalid params
- `C l r lo hi` — count of values `v` with `lo ≤ v < hi` in `s[l..r)`; `0` for invalid ranges or `lo ≥ hi`
- `V l r c` — smallest value `≥ c` in `s[l..r)`, or `-1`
- `P l r c` — largest value `≤ c` in `s[l..r)`, or `-1`

Invalid range for K/C/V/P: `l < 0`, `r > n`, `l ≥ r`. Additional for K: `k ≤ 0` or `k > r - l`.

**Constraints:** `0 ≤ n ≤ 200000`, `1 ≤ sigma ≤ 1024`, up to `500000` queries. All operations must complete within 30 seconds on the full constraint set.
