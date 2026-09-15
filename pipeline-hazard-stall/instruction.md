The MaxiCore32 processor at `/app/` is a 32-bit, two-stage pipelined CPU implemented in Verilog. Its pipeline consists of stage 1 (instruction decode in `memorystage1.v`) and stage 2 (execution/writeback in `registersstage2.v`), integrated via the top-level datapath in `maxicore32.v`.

The processor currently has no hardware interlock for data hazards. When an instruction writes to a register and the immediately following instruction reads that same register, the read obtains a stale value because the register file write has not yet completed. This requires programmers to manually insert NOP instructions after every register-writing operation, wasting approximately 20% of instruction slots.

Implement automatic pipeline hazard detection and stalling in the MaxiCore32 processor so that programs execute correctly without manually inserted NOPs.

The hazard detection must handle Read-After-Write (RAW) dependencies for at least these instruction types:
- `LOADI` (immediate load) writing a destination register
- `ALUM` / `ALUMI` / `ALU` (arithmetic/logic) writing a destination register

When a hazard is detected, the pipeline must stall: freeze the program counter and inject a NOP bubble into stage 1 so the in-flight write completes before the dependent instruction reads the register.

The Verilog source is in `/app/src/`, the testbench in `/app/tb/`, and pre-encoded test programs (hex) in `/app/programs/`. Use `iverilog` for compilation and `vvp` for simulation. The memory module loads `/app/program.hex` via `$readmemh`.

After your modification:
- `/app/programs/nop_test.hex` (regression test with manual NOPs) must still halt with r1=5, r2=10, r3=15, r4=25.
- `/app/programs/hazard_chain_test.hex` (chain of dependent ops, no NOPs) must halt with r1=5, r2=10, r3=15, r4=25.
- `/app/programs/mixed_hazard_test.hex` (LOADI→ALU, ALU→ALU, ALU→ALUMI hazards interleaved with non-dependent instructions) must halt with r1=7, r2=3, r3=10, r4=1, r5=9, r6=16, r7=18.