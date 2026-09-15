An incomplete draft pipeline at `/app/draft_pipeline.py` attempts to characterize a logical T gate in the [[7,1,3]] Steane code using `bloqade-tsim`. The draft's noiseless circuit produces non-zero detector firing rates, indicating errors in the encoding gate sequence, stabilizer detector annotations, and/or logical observable definition. The pipeline is also missing noise modeling, detector error model extraction, syndrome decoding, gate equivalence verification, and structured JSON output.

Diagnose and fix the circuit construction bugs, then build a complete analysis pipeline at `/app/pipeline.py` that writes correct results to `/app/results.json`.

## Output specification

`/app/results.json` must be valid JSON containing these top-level keys with the specified fields and constraints:

**`circuit_properties`**: `num_qubits` (==7), `num_measurements` (==7), `num_detectors` (==3), `num_observables` (==1), `t_count` (≥1), `is_clifford` (==`false`)

**`noiseless_analysis`**: `observable_flip_rate` (sampled over sufficient shots, must be within ±0.02 of `ideal_rate`), `detector_firing_rate` (must be exactly 0.0 for a correct noiseless circuit), `ideal_rate` (exact theoretical flip probability for the circuit's logical T-gate operation — derive this value from the gate's rotation angle and the measurement basis)

**`equivalence_check`**: `t_observable_rate`, `rz_observable_rate` — replacing the T gate with `R_Z(0.25)` must yield observable flip rates that differ by < 0.02

**`dem_analysis`**: `num_error_mechanisms` (≥3), `total_error_probability` (>0), `max_mechanism_weight` (≤4) — extracted from the detector error model of the circuit with circuit-level depolarizing noise added at physical error rate p=0.001

**`noisy_analysis`**: `physical_error_rate` (must be in (0,1)), `raw_observable_flip_rate`, `decoded_observable_flip_rate` (after applying syndrome-based error correction using the DEM), `detector_firing_rate` (must be >0 under noise), `post_selected_observable_flip_rate` (within ±0.03 of the noiseless ideal rate; computed using only shots with zero detector events; `null` if no shots qualify), `raw_deviation_from_ideal`, `decoded_deviation_from_ideal` (must satisfy: `decoded_deviation_from_ideal` ≤ `raw_deviation_from_ideal` + 0.005), `decoder_provides_improvement` (boolean)

**`dual_t_analysis`**: `noiseless_observable_flip_rate` (within ±0.02 of 0.5), `ideal_rate` (==0.5) — for a variant circuit applying T twice before encoding