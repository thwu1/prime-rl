Time-history output data from an OpenRadioss explicit dynamics frontal crash simulation is in `/sim_output/`. The data includes energy component histories (`energy_th.csv`) and nodal acceleration measurements (`accel_node42_th.csv`). Simulation metadata is in `/sim_output/metadata.json`. Lines beginning with `#` in the CSV files are comments; data columns are whitespace-separated.

Build a post-processing analysis tool runnable via `python3 /app/crashdiag/main.py` that produces a diagnostic JSON report at `/app/results/report.json` containing:

- `energy_balance`: object with `max_error_pct` (float, percentage), `first_violation_time` (float in seconds, or null if energy error never exceeds 2% of initial total energy), and `error_source` (one of `"hourglass"`, `"contact"`, `"numerical"` — classify based on which energy component drives the imbalance)
- `peak_accelerations`: object mapping CFC class labels (`"CFC60"`, `"CFC180"`, `"CFC600"`, `"CFC1000"`) to peak resultant filtered acceleration in g, using SAE J211/1 Channel Frequency Class filtering
- `hic`: object with `hic15` and `hic36` values (Head Injury Criterion) computed from CFC180-filtered resultant acceleration
- `assessment`: `"PASS"` if HIC15 < 700 AND HIC36 < 1000 AND max energy error < 5%, otherwise `"FAIL"`

Total energy at each timestep is the sum of all energy components in the data. Energy error is `(total(t) - total(0)) / total(0) * 100`.