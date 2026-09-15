Compute non-equilibrium steady-state heat currents through a two-qubit system coupled to two bosonic heat baths at different temperatures. The system-bath coupling is non-perturbative for larger coupling values, so a method capable of handling strong coupling and non-Markovian effects is required.

## System

Two coupled qubits (units: hbar = k_B = 1):

    H_S = (eps/2)(sigma_z^1 + I) x I + I x (eps/2)(sigma_z^2 + I) + J12 (sigma_+^1 sigma_-^2 + sigma_-^1 sigma_+^2)

Parameters: eps = 1.0, J12 = 0.05. Bath coupling operators: Q_1 = sigma_x x I, Q_2 = I x sigma_x. Drude-Lorentz spectral density: J_K(w) = 2 * lam * gamma_K * w / (gamma_K^2 + w^2).

- Bath 1 (hot, coupled to qubit 0): T = 2.5, gamma = 3.0
- Bath 2 (cold, coupled to qubit 1): T = 1.5, gamma = 3.0

## Task

For each coupling strength lam in {0.005, 0.0125, 0.025, 0.05, 0.1, 0.2}, compute the non-equilibrium steady-state density matrix and extract the bath heat currents j_B^K = d/dt <H_B^K>. The results should exhibit turnover behavior: |j_B^1| is non-monotonic in lam. Ensure converged numerics so that energy conservation holds at steady state (|j_B^1 + j_B^2| << |j_B^1|).

## Output

Write `/app/results.json`:

```json
{
  "steady_state_sigma_z1": <float>,
  "heat_currents": [
    {"lambda": 0.005, "j_B1_real": <float>, "j_B2_real": <float>},
    {"lambda": 0.0125, "j_B1_real": <float>, "j_B2_real": <float>},
    {"lambda": 0.025, "j_B1_real": <float>, "j_B2_real": <float>},
    {"lambda": 0.05, "j_B1_real": <float>, "j_B2_real": <float>},
    {"lambda": 0.1, "j_B1_real": <float>, "j_B2_real": <float>},
    {"lambda": 0.2, "j_B1_real": <float>, "j_B2_real": <float>}
  ],
  "peak_lambda": <float>,
  "peak_current_abs": <float>,
  "energy_conservation_error": <float>
}
```

- `steady_state_sigma_z1`: Tr(sigma_z^1 rho_ss) at lam = 0.025
- `j_B1_real`, `j_B2_real`: real parts of bath heat currents
- `peak_lambda`: lam that maximizes |j_B^1| across the scanned couplings
- `peak_current_abs`: maximum |j_B^1|
- `energy_conservation_error`: |Re(j_B^1) + Re(j_B^2)| / |Re(j_B^1)| at lam = 0.025