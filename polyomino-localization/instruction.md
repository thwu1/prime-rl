Polyomino shapes of known geometry have been placed at unknown positions on a 20x20 grid without overlapping. Noisy aggregate measurements over rectangular subregions report the count of occupied cells in each rectangle, corrupted by additive Gaussian noise with standard deviation `noise_sigma * sqrt(region_size)`, then clamped to non-negative values.

Instance data is spread across three formats in `/app/`:

- `/app/config.toml` — grid dimensions and noise parameters
- `/app/shapes/instance_{i}/poly_{j}.csv` — each CSV defines one polyomino's cell offsets relative to its origin
- `/app/data.db` — SQLite database containing measurement regions and noisy observed values; explore the schema with the `sqlite3` CLI

Build a solver pipeline that integrates these heterogeneous data sources, infers each polyomino's grid placement via optimization, and writes results to a new SQLite database at `/app/results.db` containing a `solutions` table:

```sql
CREATE TABLE solutions (
    instance_id INTEGER NOT NULL,
    row INTEGER NOT NULL,
    col INTEGER NOT NULL,
    value INTEGER NOT NULL CHECK(value IN (0, 1)),
    PRIMARY KEY (instance_id, row, col)
);
```

All 400 cells (rows 0-19, cols 0-19) for each of the 8 instances (instance_id 0-7) must be present. The predicted binary grids must achieve an average F1 score >= 0.85 across all instances.