Implement a Spectral Deferred Correction (SDC) solver and produce numerical analysis results in `/app/results.json`.

Reference material on SDC methods is available in this environment. Explore it to understand the mathematical framework well enough to build your own solver from scratch.

## Required results in `/app/results.json`

| Key | Type | Description |
|-----|------|-------------|
| `nodes_M3` | sorted array | 3 Gauss-Radau IIa collocation nodes on [0,1] |
| `nodes_M5` | sorted array | 5 Gauss-Radau IIa collocation nodes on [0,1] |
| `Q_M3` | 3×3 nested array (row-major) | Spectral integration matrix Q for the M=3 nodes |
| `convergence_orders` | `{"1": p1, ..., "5": p5}` | Observed global convergence order for M=3 SDC with K=1..5 correction sweeps, applied to u'(t) = −u(t), u(0) = 1, t ∈ [0,1], using N = 4, 8, 16, 32, 64 uniform time steps; order = log₂(e₃₂/e₆₄) where eₙ = |uₙ(1) − e⁻¹| |
| `stability_R` | `{"-0.5": R1, ..., "-10.0": R5}` | SDC stability function R(z) for M=3, K=3 correction sweeps, using the standard implicit-Euler-based sweep preconditioner, evaluated at z = −0.5, −1.0, −2.0, −5.0, −10.0 |
| `optimal_diag_entries` | [d₁, d₂, d₃], dᵢ > 0 | Diagonal preconditioner entries that minimize the spectral radius of the SDC iteration matrix for the M=3 integration operator |
| `optimal_spectral_radius` | float | The achieved minimum spectral radius |

Create your implementation scripts in `/app/`.