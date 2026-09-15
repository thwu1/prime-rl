A two-qubit quantum system is connected to two independent bosonic heat baths at different temperatures. When the system-bath coupling strengths are asymmetric (λ₁ ≠ λ₂), the device acts as a thermal diode: the magnitude of steady-state heat current depends on the direction of the temperature bias.

## System

Two coupled qubits with Hamiltonian (ℏ = k_B = 1):

    H_S = (ε/2)(σ_z⁽¹⁾ + I) ⊗ I  +  I ⊗ (ε/2)(σ_z⁽²⁾ + I)  +  J₁₂(σ₊⁽¹⁾σ₋⁽²⁾ + σ₋⁽¹⁾σ₊⁽²⁾)

Each qubit k couples to its own independent Drude-Lorentz bosonic bath with spectral density J_k(ω) = 2λ_k γ ω / (ω² + γ²) via the coupling operator Q_k = σ_x⁽ᵏ⁾.

All parameters are in `/app/system_params.json`. For each coupling asymmetry ratio α listed there, set λ₁ = λ_base and λ₂ = α × λ_base.

## Problem

A simulation at `/app/initial_simulation.py` attempts to compute steady-state heat currents and thermal rectification for this system but produces incorrect results. Diagnose what is wrong with the approach and produce physically correct results that satisfy all acceptance criteria below.

QuTiP 5.3.0 is available in the environment.

## Output

Write three JSON files to `/app/results/`:

**`steady_state_currents.json`** — For each asymmetry ratio α (string key matching the parameter file, e.g. `"0.25"`), report the through-current magnitude (|j_B¹|, where j_B¹ is the heat current of bath 1) for forward bias (T₁=T_hot, T₂=T_cold) and reverse bias (T₁=T_cold, T₂=T_hot):
```json
{"0.25": {"j_forward": <positive float>, "j_reverse": <positive float>}, ...}
```

**`rectification.json`** — Rectification coefficient R = (j_forward − j_reverse) / max(j_forward, j_reverse) for each α:
```json
{"0.25": <float>, ...}
```

**`energy_conservation.json`** — Relative energy conservation error |j_B¹ + j_B²| / max(|j_B¹|, |j_B²|) for each α and bias direction:
```json
{"0.25": {"forward": <float>, "reverse": <float>}, ...}
```

## Acceptance Criteria

- All `j_forward` and `j_reverse` values must be strictly positive
- Energy conservation error must be below 0.01 for every configuration
- For symmetric coupling (α = 1.0), |R| must be below 0.02
- Rectification values must equal (j_forward − j_reverse) / max(j_forward, j_reverse) for each α
- Results for α = 2.0 will be independently verified to within 0.1% relative tolerance