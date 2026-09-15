In the Lux AI Season 3 game engine, hidden energy nodes on a 24×24 grid emit energy fields computed via parameterized mathematical functions of Euclidean distance. The complete specification of the energy field computation — including the two function types, the distance metric, the mean-adjustment rule, rounding, and clipping — is at `/app/specs.md`.

Observation data from five game scenarios with increasing difficulty is at `/app/data/scenario_{1..5}.json`. Each scenario provides partial fog-of-war observations (a subset of tiles with their exact integer energy values) along with the number of active symmetric node pairs (1–3). Scenarios range from 80% tile coverage with a single node pair to 30% coverage with three overlapping pairs using mixed function types.

Reconstruct the complete 24×24 integer energy field for each scenario by inferring the positions, function types, and parameters of the hidden energy nodes. Write results to `/app/results/scenario_{i}.json`, each containing:

```json
{"energy_field": [[e_00, e_01, ...], [e_10, ...], ...]}
```

where `energy_field[x][y]` is the energy value at grid position (x, y), an integer in [−20, 20].