A ring oscillator-based measurement circuit in `/app/` is designed to characterize the relative performance of different parallel prefix adder architectures (Kogge-Stone, Brent-Kung, Sklansky) against a ripple-carry baseline. The project contains algorithmic bugs in the prefix tree computations, a non-functional ring oscillator, an incomplete top-level module, and a missing adder implementation.

The RTL source is in `/app/rtl/`. Testbenches are in `/app/tb/`. A `Makefile` provides `test_*` and `synth_*` targets. Tools available: `iverilog`, `vvp`, `yosys`, `python3`.

Fix all bugs so that every adder passes exhaustive functional verification (all 2^16 x 2 input combinations for 8-bit operands with cin in {0,1}), the ring oscillator produces free-running oscillation when enabled, and the measurement counter in the characterizer does not overflow during long integration periods. Implement the Sklansky parallel prefix adder from scratch (the current file is a stub). Run Yosys synthesis on each adder architecture.

Write results to `/app/results/analysis.json`:
```json
{
  "adders": {
    "<name>": {"cell_count": <int>, "correct": true}
  },
  "area_ranking": ["<smallest>", ..., "<largest>"],
  "ring_oscillator_functional": true
}
```
Adder keys: `ripple_carry`, `kogge_stone`, `brent_kung`, `sklansky`. Cell counts come from Yosys `stat` output. Synthesis logs: `/app/results/<module_name>_synth.log`.