A pipelined integer computation block at `/app/rtl/compute_pipeline.sv` computes `isqrt(a*a + b*b) + c` using arithmetic sub-blocks defined in `/app/rtl/blackbox/`. The pipeline accepts and produces one data word per cycle but has no backpressure support — when a downstream consumer is not ready, pipeline outputs are silently dropped.

Implement `/app/rtl/flow_control_wrapper.sv` that wraps this pipeline so the combined module operates correctly under arbitrary downstream stalling, without any data loss, corruption, or reordering.

## Interface

The module skeleton is already declared in the file. Ports:

- **Input**: `arg_vld`/`arg_rdy` handshake with data ports `a`, `b`, `c` (each 32 bits). A transfer occurs on a rising clock edge when both `arg_vld` and `arg_rdy` are high.
- **Output**: `res_vld`/`res_rdy` handshake with `result` (32 bits). Same transfer semantics.

## Requirements

- The wrapper must internally instantiate the `compute_pipeline` module — do not reimplement or bypass the existing pipeline logic.
- The wrapper must include internal output buffering (e.g. a FIFO with read/write pointers or head/tail indices and a memory array) to capture pipeline results and hold them while the consumer stalls.
- No data may be lost or corrupted under any sequence of `res_rdy` deassertion.
- Results appear at the output in the same order as their corresponding inputs.
- `arg_rdy` must be high immediately after reset completes, before any `arg_vld` is driven.
- Sustained throughput of one result per cycle when the consumer never deasserts `res_rdy`.

## Verification

The design must compile cleanly with Icarus Verilog using the SystemVerilog 2012 standard (`iverilog -g2012`). All source files under `/app/rtl/` and the testbench at `/app/tb/tb_flow_control.sv` are compiled together.

Run `/app/simulate.sh` to compile and simulate against the provided testbench. The simulation must print `PASS` and must not print `FAIL`. The testbench drives multiple phases including idle ready-check, single transaction, back-to-back throughput, sustained backpressure, random backpressure with concurrent producer/consumer, and burst-then-drain.