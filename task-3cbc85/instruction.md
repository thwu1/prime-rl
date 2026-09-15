Implement a scaled dot-product attention kernel with causal masking for the VecTor-16 custom vector accelerator. The kernel must produce numerically correct output when executed on the provided ISA simulator.

The VecTor-16 ISA simulator is at `/app/simulator/sim.py`. ISA documentation is at `/app/docs/isa_reference.md`. The memory layout specification is at `/app/docs/memory_layout.md`. Example kernels are in `/app/examples/`.

Write your kernel to `/app/kernels/attention.asm`.

The kernel computes single-head scaled dot-product attention over a pre-filled KV cache with causal masking. Compute attention scores as the scaled dot product of the query with each key vector, apply a causal mask that sets future positions to negative infinity, apply softmax to obtain attention weights, and compute the output as the weighted sum of value vectors. The softmax implementation must be numerically stable — naive exponentiation will overflow and produce incorrect results.

Parameters: head dimension d_k=32, KV cache sequence length 8, number of valid (unmasked) positions loaded from memory. The vector register length is 16 elements, requiring tiled processing across two tiles per vector.

Verify your kernel: `pip3 install numpy && cd /app && python3 test_harness.py`