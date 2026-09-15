Satellite NORAD 52140 orbits in the low-Earth environment where thermospheric drag is the dominant non-gravitational perturbation. During geomagnetic storms, Joule heating and particle precipitation enhance thermospheric density at orbital altitudes, intensifying drag losses. Three standard geomagnetic indices — **ap**, **Dst**, and **AE** — each reflect different magnetospheric current systems and respond to solar wind forcing on different timescales.

The following data are provided:

- `/app/data/geomag_2024.db` — SQLite database containing hourly geomagnetic and solar activity indices in a normalized schema with multiple tables. Use `sqlite3` to explore the schema and extract data. The three geomagnetic indices of interest are stored in the `geomag_indices` table; epoch timestamps are in the `epoch_info` table. NULL values indicate missing measurements.

- `/app/data/omm_52140.json` — Satellite orbital data in **CCSDS Orbit Mean-elements Message (OMM) JSON format** — the standard used by Space-Track.org. Each record contains fields such as `EPOCH`, `MEAN_MOTION` (rev/day), `ECCENTRICITY`, `INCLINATION`, etc. Use `jq` to explore the structure and extract the orbital elements needed. This is NOT a standard two-line element file.

Determine which of the three geomagnetic indices most strongly predicts this satellite's natural orbital decay rate during **May 2024**, and find the optimal response lag between geomagnetic disturbance and observed orbital decay. The orbital history includes both natural drag decay and station-keeping maneuvers; the geomagnetic database contains epochs with missing measurements.

Store results in a new table `correlation_results` in the SQLite database `/app/data/geomag_2024.db` with columns: `best_index TEXT, best_lag_hours INTEGER, best_r_squared REAL, n_data_points INTEGER` (one row).

Also write `/app/results.json`:
```json
{
    "best_index": "<name of the strongest predictor among ap, Dst, AE>",
    "best_lag_hours": <optimal lag in whole hours>,
    "best_r_squared": <r-squared at the optimal lag, 4 decimal places>,
    "n_data_points": <number of matched observation pairs at the optimal lag>
}
```