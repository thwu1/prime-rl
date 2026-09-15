`/app/verilog/` contains the full SystemVerilog RTL for a minimal GPU architecture. `/app/kernels/` has example assembly programs targeting this GPU.

Reverse-engineer the hardware design from the Verilog source and implement two Python modules:

**`/app/assembler.py`** — `assemble(source: str) -> dict` that translates GPU assembly text into machine code. Returns `{'program': list[int], 'data': list[int], 'threads': int}` — encoded instruction words, initial data-memory values from `.data` directives, and thread count from `.threads` directive (0 if absent).

**`/app/simulator.py`** — `simulate(program: list[int], data: list[int], thread_count: int, num_cores: int = 2, threads_per_block: int = 4) -> dict` that functionally executes a GPU kernel. Returns `{'data_memory': list[int], 'num_blocks': int}` — complete data memory state after execution and number of thread blocks dispatched.

Both modules must be behaviorally faithful to the Verilog. Every instruction encoding, register behavior, arithmetic semantic, memory operation, thread scheduling policy, and control-flow mechanism must exactly match what the hardware defines. The Verilog modules are the sole authoritative specification.