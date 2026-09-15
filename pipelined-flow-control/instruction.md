Implement the pipelined computation block in `/app/compute.sv`. The module computes the formula:

```
result = isqrt(a*a + b*b) + a*b - c
```

where all values are unsigned 32-bit integers (wrapping on overflow) and `isqrt` is the integer square root (floor).

You must use **only** the arithmetic modules provided in `/app/arithmetic_blocks/` (`pipe_add`, `pipe_sub`, `pipe_mult`, `pipe_isqrt`) for all addition, subtraction, multiplication, and square-root operations. Do not implement your own arithmetic. Do not modify any file other than `/app/compute.sv`.

The module must support AXI-Stream-like valid/ready flow control with backpressure:
- Input handshake: `arg_vld` / `arg_rdy`
- Output handshake: `res_vld` / `res_rdy`
- When the block has capacity (is not stalled by backpressure), `arg_rdy` **must** be 1 — it must not wait for `arg_vld`.
- When there is no backpressure, the design must accept new inputs every clock cycle back-to-back without stalls or gaps.

The pipeline latencies of the arithmetic blocks are **not documented**. Analyze the source code in `/app/arithmetic_blocks/` to determine each module's latency, then design your pipeline schedule with correct data alignment across stages.

Run `/app/simulate` to compile and verify your design against the self-checking testbench.