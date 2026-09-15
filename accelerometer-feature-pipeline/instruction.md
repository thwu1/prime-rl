The files in `/app/` implement a two-stage accelerometer data processing pipeline built and run via `make -C /app pipeline`:

**Stage 1 -- Calibration**: `CalibratorMain` reads raw triaxial sensor data (CSV, no header, columns `x,y,z` in g-units at 100 Hz) and per-axis calibration parameters from `/app/config/calibration.properties`, applies bias and scale correction per the model `calibrated = (raw - offset) * scale`, and writes calibrated CSV output.

**Stage 2 -- Feature Extraction**: `EpochFeatureExtractor` reads calibrated data and computes 44 epoch-level features including Butterworth-filtered ENMO statistics, San Diego gravity-separated kinematic features (with EMA gravity estimation), MAD-family descriptors (MAD, MPD, skewness, excess kurtosis), arm angle metrics, and DFT-based spectral analysis (dominant frequency, peak power, spectral entropy). Output is a JSON file mapping feature names to double values.

The Makefile at `/app/Makefile` orchestrates compilation and multi-stage pipeline execution. Java sources are in `/app/src/`, calibration configuration in `/app/config/calibration.properties`.

The pipeline is currently broken. Bugs span the build system, pipeline orchestration, calibration implementation, and signal processing algorithms. Some prevent compilation or execution; others produce numerically incorrect results.

Fix all issues so that `make -C /app pipeline` completes successfully and the 44 output features in `/app/output/features.json` are numerically correct. The test validates each feature against an independently-computed reference with combined tolerance (absolute 1e-6, relative 1e-4). All 44 features must pass.

No reference values, test logic, or expected outputs are accessible from `/app/`.
