A payment gateway service distributed across four backend clusters experienced a cascading failure during a production incident. Complete operational documentation for the service is provided, along with the cluster topology, tuning parameters, and a timeline of external events that triggered the incident.

The environment contains:

- `/app/topology.yaml` — cluster definitions (capacity, routing weight, region)
- `/app/incident.db` — SQLite database with system tuning parameters (`parameters` table), the scheduled incident event timeline (`events` table), and run configuration (`metadata` table). Inspect the schema to understand the full configuration.
- `/app/system_behavior.md` — complete operational documentation for the payment gateway, describing all service behaviors, state transitions, and interaction dynamics

Using the operational documentation as the authoritative specification, reconstruct the complete state of every cluster at each time step throughout the incident and produce:

1. `/app/results.json` — time-step-by-time-step system state in the JSON format specified in the operational documentation.

2. Append to `/app/incident.db`:
   - Table `simulation_results` — columns: `time_step` (INTEGER PK), `base_load` (REAL), `total_load` (REAL), `effective_load` (REAL), `throttle_probability` (REAL), `error_rate` (REAL), `total_accepted` (REAL), `total_rejected` (REAL).
   - Table `cluster_states` — columns: `time_step` (INTEGER), `cluster_name` (TEXT), `status` (TEXT), `capacity` (REAL), `incoming` (REAL), `accepted` (REAL), `rejected` (REAL), `utilization` (REAL). Primary key: (`time_step`, `cluster_name`).
   - Table `analysis_summary` — columns: `metric` (TEXT PK), `value` (TEXT). Store each analysis metric per the documentation. List-valued metrics as comma-separated sorted strings; null values as literal string `null`.
   - View `capacity_headroom` over `cluster_states`: for each cluster (excluding ticks where the cluster was crashed), compute `min_headroom` (min of capacity minus incoming), `avg_headroom` (avg of capacity minus incoming), `overload_ticks` (count where incoming exceeded capacity).

Results must be deterministic and faithfully reflect the documented system behavior.