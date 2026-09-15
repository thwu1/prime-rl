A partially-implemented zero-noise extrapolation (ZNE) framework is at `/app/`. It processes noisy quantum circuit measurement data and extrapolates to the zero-noise limit — the expectation value a circuit would produce in the absence of hardware noise.

Measurement data for five circuits with distinct noise profiles is in `/app/data/`. A `LinearFactory` is implemented as a working reference. Three additional factory classes and the model selection function are incomplete stubs that must be completed.

Complete all stub implementations in `/app/zne_inference.py` and `/app/analyze.py` so that `python3 /app/analyze.py` runs successfully and writes `/app/results.json` with correct extrapolated values and appropriate factory selections for every circuit.

Accuracy requirements:
- Circuits A and D: extrapolated value within 1e-4 of the true zero-noise value
- Circuits B and E: within 0.02
- Circuit C: within 0.05
- The selected best factory must be `richardson` for circuits A and D
- The selected best factory must be `exponential` or `poly_exponential` for circuits B and E
- Each factory must also produce correct individual results (not only the selected best)