You are given the complete SystemVerilog source code for `tiny-gpu`, a minimal GPU implementation, in `/app/src/`. Architecture documentation is in `/app/README.md`.

Your task: build a Python functional simulator of this GPU architecture at `/app/simulator.py`.

The simulator must expose a class `TinyGPU` with the following interface:

```python
class TinyGPU:
    def __init__(self, num_cores=2, threads_per_block=4):
        ...

    def run(self, program, data, thread_count):
        """
        Execute a kernel on the simulated GPU.

        Args:
            program: list of 16-bit integers representing program memory
            data: list of 8-bit integers representing initial data memory
            thread_count: total number of threads to launch

        Returns:
            list of 256 8-bit integers representing final data memory state
        """
```

The simulator must correctly implement:
- All ISA instructions as defined in the SystemVerilog decoder and ALU modules
- The SIMD execution model with proper `blockIdx`, `blockDim`, and `threadIdx` register values
- Block dispatch: threads are grouped into blocks of `threads_per_block` size, with the last block potentially having fewer threads
- Memory load/store operations matching the LSU behavior
- Comparison and branching (CMP + BRnzp) matching the hardware's exact unsigned arithmetic behavior
- 8-bit data arithmetic with proper wrapping
- Integer division with truncation

Study the SystemVerilog source carefully. The ISA encoding format, register file layout, ALU operations, and NZP branch logic must exactly match the hardware behavior defined in those files.