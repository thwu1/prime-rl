A configuration file at `/opt/task/config.json` specifies a quantum chemistry simulation for a diatomic molecule: species, basis set, bond length scan range, number of scan points, and a noise rate. Examine the configuration, determine the appropriate qubit representation, and produce `/app/results.json` containing the molecule's ground-state potential energy surface (PES) with noisy and error-mitigated energy estimates.

## Output

Write `/app/results.json` with this schema:

```json
{
  "bond_lengths": [float, ...],
  "exact_energies": [float, ...],
  "noisy_energies": [float, ...],
  "zne_energies": [float, ...],
  "trace_energies": [float, ...],
  "equilibrium_bond_length": float,
  "equilibrium_energy": float,
  "dissociation_energy": float,
  "noise_parameters": {
    "base_noise_rate": float,
    "noise_scale_factors": [float, ...]
  }
}
```

- `bond_lengths`: Evenly-spaced bond distances (angstrom) from the config, monotonically increasing.
- `exact_energies`: Exact ground-state energies (Hartree) of the qubit Hamiltonian at each bond length.
- `noisy_energies`: Energies under simulated qubit noise at the config's base rate. Noise should attenuate Pauli-basis expectation values in a weight-dependent manner consistent with single-qubit depolarizing channels.
- `zne_energies`: Error-mitigated energies via zero-noise extrapolation over the listed scale factors.
- `trace_energies`: Tr(H)/2^n at each bond length (maximally mixed state energy).
- `equilibrium_bond_length`: Bond length (angstrom) at which `exact_energies` is minimized.
- `equilibrium_energy`: Minimum of `exact_energies`.
- `dissociation_energy`: `exact_energies[-1] - equilibrium_energy`.
- `noise_parameters.base_noise_rate`: Positive base noise rate from config.
- `noise_parameters.noise_scale_factors`: Strictly increasing list of at least 3 scale factors (first >= 1) used for ZNE.

## Acceptance Criteria

1. All energy arrays must have the same length as `bond_lengths`, all values finite.
2. The exact PES must have an interior minimum (not at first or last point), with both endpoints above the minimum.
3. `equilibrium_energy` must equal `min(exact_energies)` and `dissociation_energy` must equal `exact_energies[-1] - equilibrium_energy`.
4. Noisy energies must be biased above exact energies for at least 20 scan points and measurably different from exact energies overall.
5. Mean absolute error of `zne_energies` vs `exact_energies` must be strictly less than that of `noisy_energies`.
6. Maximum absolute error of `zne_energies` vs `exact_energies` must be below 0.1 Hartree.
7. The `zne_energies` PES minimum index must be within 2 positions of the `exact_energies` PES minimum index.