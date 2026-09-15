Three ArduPilot DataFlash binary flight logs from a multicopter fleet are at `/app/flights/` — `flight_alpha.bin`, `flight_bravo.bin`, and `flight_charlie.bin`. Each records a complete flight with a distinct failure profile. Reference: `/app/format_hint.txt` (binary format spec), `/app/param_ranges.json` (parameter validation ranges and defaults), `/app/safety_spec.json` (scoring criteria, causal fault chain rules, airworthiness classification, and fleet recommendation logic).

Parse all three binary logs, compute per-flight safety scores, reconstruct causal fault propagation chains, evaluate failsafe response timeliness, determine vehicle airworthiness, and synthesize a fleet-level operational recommendation. Write your assessment to `/app/fleet_assessment.json`:

- `per_flight` — keyed by `alpha`, `bravo`, `charlie`, each containing:
  - `total_messages`: count of parsed messages excluding FMT definitions
  - `max_altitude_m`: peak BARO Alt (float, 1 decimal)
  - `gps_score`, `ekf_score`, `vibe_score`, `param_score`, `mode_score`: sub-scores per safety_spec.json (float, 2 decimals)
  - `composite_score`: weighted composite from unrounded sub-scores (float, 2 decimals)
  - `risk_level`: `"low"`, `"moderate"`, `"high"`, or `"critical"` per risk thresholds
  - `misconfigured_params`: alphabetically sorted parameter names with final logged values outside `[min, max]` in param_ranges.json (last-write-wins for duplicates)
  - `root_cause`: earliest anomaly type — `"gps_glitch"`, `"mechanical_vibration"`, `"ekf_divergence"`, or `"none"`
  - `fault_chain`: chronological anomaly events, each with `event`, `time_sec` (integer from TimeUS), and `category` (`"primary"`, `"secondary"`, `"independent"`) per causal analysis rules — empty list if none
  - `failsafe_response_sec`: seconds between first anomaly and first autonomous mode transition (MODE Reason >= 2), or `null`
  - `failsafe_assessment`: `"timely"`, `"delayed"`, or `"not_applicable"` per thresholds
  - `airworthiness`: `"airworthy"`, `"conditional"`, or `"grounded"`
  - `required_actions`: alphabetically sorted mandatory maintenance actions per rules
- `risk_ranking` — flight names ordered most dangerous (lowest composite) to safest
- `systemic_issues` — sorted parameter names misconfigured across ALL three flights
- `corrective_actions` — keyed by flight name, mapping misconfigured parameters (sorted) to defaults from param_ranges.json
- `fleet_airworthy_count`, `fleet_conditional_count`, `fleet_grounded_count`: counts by airworthiness
- `recommended_fleet_action`: `"continue_operations"`, `"partial_ground"`, `"fleet_review"`, or `"full_ground"` per fleet rules