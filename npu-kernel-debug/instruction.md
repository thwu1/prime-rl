A MiniNPU transaction-level simulator at `/opt/npu/simulator.py` has implementation bugs causing incorrect instruction behavior. The ISA specification is at `/opt/npu/spec.md`. Two example programs are in `/opt/npu/programs/`. Fix the simulator to conform to the specification.

Then author three assembly kernels in `/opt/npu/programs/`:

- **dotproduct.asm** — Dot product of two 64-element vectors. Inputs at word addresses 0-63 and 64-127. Store the scalar result at address 128.
- **softmax.asm** — Numerically-stable softmax over 64 elements. Input at addresses 0-63, output at 64-127.
- **rmsnorm.asm** — RMSNorm with learned weights over 64 elements. Input at 0-63, weights at 64-127, output at 128-191. Use epsilon = 1e-6.

All kernels must produce output matching reference implementations within float32 tolerance.