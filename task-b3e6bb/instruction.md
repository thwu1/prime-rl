Rotated surface code circuits at distances 3 and 5 are pre-generated at `/app/circuits/` using Stim. The circuits model Z-memory experiments under circuit-level depolarizing noise (p=0.005).

A skeleton `StimDecoder` class exists at `/app/decoder.py`. Implement this class so it accepts a `stim.DetectorErrorModel` and decodes batches of detection events into predicted observable flips. The class must expose `__init__(self, dem)` and `decode_batch(self, detection_events, num_observables)` returning a boolean numpy array of shape `(num_shots, num_observables)`.

A skeleton benchmark script exists at `/app/benchmark.py`. Implement it to load each circuit listed in `/app/config.json`, sample detection events, decode them with `StimDecoder`, compute logical error rates by comparing predicted observables against actual observables, and write results to `/app/results.json`.

The decoder must achieve logical error rates below the thresholds specified in `/app/config.json` and demonstrate threshold behavior (d=5 must outperform d=3).

## `results.json` output schema

The output file `/app/results.json` must be a JSON object conforming to the schema defined in `/app/results_schema.json`. Each top-level key is a benchmark identifier string (e.g. `"d3_p0005"`). The value for each key must be an object with the following required fields:

| Field                | Type    | Constraints                    | Description                                         |
|----------------------|---------|--------------------------------|-----------------------------------------------------|
| `distance`           | integer | > 0                            | Code distance of the surface code circuit            |
| `noise`              | number  | 0 < noise < 1                  | Physical error probability used in the circuit       |
| `logical_error_rate` | number  | 0.0 <= value <= 1.0            | Fraction of shots with at least one logical error    |
| `num_shots`          | integer | > 0                            | Number of Monte Carlo shots used for estimation      |
| `threshold`          | number  | 0.0 < value <= 1.0             | Maximum acceptable logical error rate                |
| `passed`             | boolean |                                | `true` iff `logical_error_rate < threshold`          |

All six fields are required for every benchmark entry. No additional top-level keys outside of benchmark entries are permitted.