Implement an RF network cascade and renormalization pipeline. Running `python3 /app/process.py` must read `/app/config.json` and produce all output files in `output_dir`.

**Build prerequisite:** Compile `/app/matrix_ops.c` into `/app/libmatrix.so` by running `make -C /app`. The library exports complex 2x2 matrix primitives (see `/app/matrix_ops.h`). Your pipeline must load this shared library and use its exported functions for all 2x2 complex matrix arithmetic via foreign function interface.

**Input Files:**

`/app/network_a.s2p` — Touchstone v1.0 2-port in dB-angle (DB) format, 50 Ohm uniform reference. Legacy 2-port column ordering.

`/app/network_b.ts` — Touchstone v2.0 2-port in real-imaginary (RI) format with `[Two-Port Data Order] 12_21` and per-port reference impedances via `[Reference]`, overriding the option-line `R` value. Both files share identical frequency points.

`/app/config.json` specifies input paths, `target_impedance_ohm`, and `output_dir`.

**Processing:** Parse both files per their respective Touchstone specification versions, correctly handling dB-to-linear format conversion, column ordering differences, per-port reference impedances, inline comments, and blank lines. Cascade the two networks (A then B) into a single 2-port, resolving reference-impedance mismatches. Renormalize the cascade to `target_impedance_ohm`. Compute the impedance (Z) parameter matrix and frequency-domain metrics from the final S-parameters.

**Output Files** (all in `output_dir`):

`cascade_sparams.json`:
```json
{"reference_impedance_ohm": <float>, "frequencies_ghz": [...], "s_parameters": [{"freq_ghz": <f>, "S11_re": <f>, "S11_im": <f>, "S12_re": <f>, "S12_im": <f>, "S21_re": <f>, "S21_im": <f>, "S22_re": <f>, "S22_im": <f>}, ...]}
```

`z_matrix.json`:
```json
{"frequencies_ghz": [...], "z_parameters": [{"freq_ghz": <f>, "Z11_re": <f>, "Z11_im": <f>, "Z12_re": <f>, "Z12_im": <f>, "Z21_re": <f>, "Z21_im": <f>, "Z22_re": <f>, "Z22_im": <f>}, ...]}
```

`metrics.json`:
```json
{"frequencies_ghz": [...], "insertion_loss_db": [...], "return_loss_db": [...]}
```
Where `insertion_loss_db[i] = 20 * log10(|S21[i]|)` and `return_loss_db[i] = -20 * log10(|S11[i]|)`.

`cascade_output.ts` — Valid Touchstone v2.0 file containing the renormalized cascade S-parameters in RI format with `12_21` data ordering, all mandatory v2.0 keywords (`[Version]`, `[Number of Ports]`, `[Two-Port Data Order]`, `[Number of Frequencies]`, `[Reference]`, `[Network Data]`, `[End]`), and correct reference impedance.

`frequency_response.svg` — SVG plot produced by `gnuplot` showing insertion loss (dB) and return loss (dB) versus frequency (GHz) for the cascaded network, with labeled axes and a legend distinguishing the two curves.
