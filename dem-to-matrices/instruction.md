A skeleton module at `/app/qec_decoder.py` defines a `DemMatrices` dataclass and three function stubs. Implement all three functions so the module provides a working end-to-end decoding pipeline for quantum error correction.

**`detector_error_model_to_check_matrices(dem)`** — Given a `stim.DetectorErrorModel`, produce a `DemMatrices` instance whose six sparse matrices and priors vector correctly encode the error model's structure. The `DemMatrices` dataclass docstring in the skeleton specifies the semantics of each field. The conversion must correctly handle multi-component error instructions (those containing `^` separators), repeated error instructions that share the same detector signature, `repeat` blocks, boundary errors (touching zero detectors), and weight-1 errors.

**`build_decoder(dem_matrices, ...)`** — Construct a decoder from the matrices and priors in `DemMatrices`. The decoder must expose a `.decode(syndrome)` method. Use the `ldpc` library.

**`decode_batch(decoder, dem_matrices, detection_events)`** — Given a decoder and a batch of binary detection-event rows, return a `(num_shots, num_observables)` `uint8` array of predicted logical observable flips.

Pre-installed libraries: `stim`, `ldpc`, `numpy`, `scipy`. Example DEM files are at `/app/dem_files/`. Do NOT use `stimbposd`, `beliefmatching`, or `pymatching`.