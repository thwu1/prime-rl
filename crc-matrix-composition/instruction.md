`/app/spec.json` defines a CRC algorithm with non-standard parameter combinations, test vectors, and composition operations.

Create `/app/crc_module.py` that provides:

- `CRCProcessor`: an Amaranth HDL `Elaboratable` implementing the specified CRC in hardware. Constructor accepts a dict with integer-valued keys (`crc_width`, `polynomial`, `initial_crc`, `reflect_input`, `reflect_output`, `xor_output`, `data_width`). Exposes `start`, `data`, `valid`, and `crc` signal attributes.

- `compose_crc(crc_a, data_b, spec) -> int`: given CRC(A) and raw data B, returns CRC(A||B) without access to A's original data.

- `compute_residue(spec) -> int`: returns the CRC residue value.

Running `python3 /app/crc_module.py` must simulate the `CRCProcessor` using the Amaranth simulator with all test vectors and write to `/app/output/`:

- `hw_simulation.vcd` -- simulation waveform
- `crc_values.json` -- `{"tv1": <int>, ..., "tv5": <int>}`
- `f_matrix.json` -- the processor's n x n state-transition matrix (list of lists of 0/1)
- `g_matrix.json` -- the processor's m x n input-to-state matrix (list of lists of 0/1)
- `composed_crcs.json` -- `{"comp1": <int>, "comp2": <int>, "comp3": <int>}`
- `residue.txt` -- single integer