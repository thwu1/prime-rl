The directory `/app/src/` contains the complete SystemVerilog source for a minimal GPU called tiny-gpu. An ISA reference is at `/app/docs/isa.md`.

Reverse-engineer the GPU architecture from these Verilog source files and produce two Python modules:

**`/app/assembler.py`** — Export a function `assemble(source: str) -> list[int]` that converts tiny-gpu assembly source code into a list of 16-bit machine code words. The assembler must handle all instruction types defined by the hardware, register operands (including any special-purpose registers), label definitions and references, immediate values, comments (`;` to end of line), and assembler directives (which should be ignored in code generation).

**`/app/simulator.py`** — Export a class `TinyGPU` that faithfully replicates the GPU's execution behavior:

```python
class TinyGPU:
    def __init__(self, num_cores=2, threads_per_block=4,
                 data_mem_channels=4, program_mem_channels=1): ...
    def load_program(self, program: list[int]) -> None: ...  # 16-bit words
    def load_data(self, data: list[int]) -> None: ...         # 8-bit values
    def run(self, thread_count: int) -> dict: ...
    # Returns {'data_memory': list[int] (256 entries), 'cycles': int}
```

The Verilog source files are the ground truth for all architectural behavior. Your implementations must match the hardware's instruction encoding, execution semantics, thread scheduling, and memory access patterns as defined by those modules.