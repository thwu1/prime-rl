Implement an online learning library at `/app/pfol/` (Python package) and a foreign-function wrapper for the provided C adversarial-sequence generator at `/app/lib/`. All classes must be importable from `pfol`.

**Provided environment:**
- `/app/lib/adversary.c`, `/app/lib/adversary.h` — C library for deterministic adversarial sequence generation and theoretical bound computation
- `/app/Makefile` — builds `/app/lib/libadversary.so`
- `/app/data/scenarios.json` — benchmark test configurations

**Required classes and behavioral contracts:**

`KTBettor(epsilon: float = 0.0)` — `.bet() -> float` in [-1,1]; `.update(coin: float)` for coin in [-1,1]; `.wealth() -> float` always >= 0. On balanced T-length sequences, wealth >= C/sqrt(T) for universal C > 0. On constant-bias sequences, wealth grows super-polynomially.

`OneDimOLO(lipschitz: float = 1.0)` — `.predict() -> float`; `.update(grad: float)`; `.cumulative_regret(competitor: float) -> float`. Regret vs competitor u over T rounds must be O(|u| * sqrt(T * log(|u| * sqrt(T) + e))).

`CoordOCO(dim: int, lipschitz: float = 1.0)` — `.predict() -> list[float]`; `.update(grad: list[float])`; `.cumulative_regret(competitor: list[float]) -> float`. Must equal sum of independent per-coordinate 1-d regrets.

`CBCE(dim: int, lipschitz: float = 1.0)` — `.predict() -> list[float]`; `.update(grad: list[float])`; `.interval_regret(start: int, end: int, competitor: list[float]) -> float` with regret O(sqrt(n) * polylog(T)) on any sub-interval of length n; `.num_active_learners() -> int` must be O(log t) at round t.

`BoundsChecker()` — wraps `/app/lib/libadversary.so` via ctypes. Methods: `.generate_sequence(seed: int, T: int, dim: int) -> list[list[float]]`; `.olo_bound(competitor: float, T: int, lipschitz: float) -> float`; `.adaptive_bound(interval_len: int, T: int) -> float`; `.wealth_bound(T: int) -> float`. Must call the corresponding C functions.

**Success criteria:**
- `make -C /app` builds the shared library without errors
- `python3 -c "from pfol import KTBettor, OneDimOLO, CoordOCO, CBCE, BoundsChecker"` succeeds
- `BoundsChecker` loads and correctly invokes the compiled shared library
- All behavioral bounds pass deterministic verification
