A SQLite database at `/app/replays.db` contains replay data from the Lux AI Season 3 competitive game engine. Each replay records full omniscient game state at every timestep across a multi-match game, but the **hidden game parameters** have been stripped. State snapshots and action records are stored as **gzip-compressed JSON blobs** in the database.

Write `/app/infer_params.py` that reads replay data from the database, analyzes state transitions to reverse-engineer the hidden parameters, and submits results using the `/app/replay-tool submit` CLI command. This command writes inferred parameters to both `/app/results/replay_N.json` and the `results` table in the database — both outputs are required for verification to pass.

## Resources

- Game specification: `/app/specs.md`
- Database CLI tool: `/app/replay-tool --help` (also available as `replay-tool` in PATH)
- Database exploration: `sqlite3 /app/replays.db` and `replay-tool schema`
- An example replay (ID 99) is stored in the database with all parameters visible in `known_params`, including the normally hidden ones — use it for format reference and self-validation.
- A standalone JSON export of the example is at `/app/example_replay.json`.

## Hidden Parameters to Infer

For each non-example replay in the database, infer these 7 parameters:

| Parameter | Possible Values |
|---|---|
| `nebula_tile_drift_speed` | -0.15, -0.1, -0.05, -0.025, 0.025, 0.05, 0.1, 0.15 |
| `nebula_tile_energy_reduction` | 0, 1, 2, 3, 5, 25 |
| `nebula_tile_vision_reduction` | 0, 1, 2, 3, 4, 5, 6, 7 |
| `unit_sap_dropoff_factor` | 0.25, 0.5, 1.0 |
| `unit_energy_void_factor` | 0.0625, 0.125, 0.25, 0.375 |
| `energy_node_drift_speed` | 0.01, 0.02, 0.03, 0.04, 0.05 |
| `energy_node_drift_magnitude` | 3, 4, 5 |

## Data Access

Replay data is in a multi-table SQLite database. Use `replay-tool schema` to see the table definitions. Key points:

- `states.data` and `actions.data` columns contain **gzip-compressed JSON** — you must decompress before parsing.
- Observable parameters are in the `known_params` table (one row per param per replay).
- Use `replay-tool export-state <id> <step>` to inspect individual decompressed states.
- Use `replay-tool params <id> --json` to get known parameters as JSON.
- Use `replay-tool list` to see available replays and their IDs.

## State Data Format (after decompression)

Each state snapshot contains: `units` (position/energy), `units_mask`, `map_features` (tile_type/energy), `energy_nodes`, `vision_power_map`, `team_points`, `team_wins`, `steps`, `match_steps`.

## Submission

For each replay ID `N`, create a JSON file containing the 7 inferred parameter values and submit:
```
/app/replay-tool submit N /path/to/result.json
```
Verification checks both the JSON files at `/app/results/` and the `results` table in the database.