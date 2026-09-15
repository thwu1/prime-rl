A VLIW (Very Long Instruction Word) machine simulator and a custom assembly toolkit are provided under `/app/`. Three test programs are provided as `.vasm` files in `/app/programs/`.

Each program consists of sequential instructions using an unbounded set of virtual registers, executing one instruction per cycle. Your goal is to implement `/app/optimize.py` so that each program can execute in fewer cycles on the VLIW machine while using only a bounded number of physical registers.

The `optimize(instructions, max_regs)` function must accept a list of instruction dicts (as produced by `vliwc parse`) and a physical register limit. It must return a list of VLIW bundles — each bundle being a list of instruction dicts using physical register numbers within the given budget. The machine executes all instructions in a bundle simultaneously in one cycle.

Each test program specifies target limits for both physical register count and cycle count. The optimizer must meet both targets while preserving functional correctness — the memory state after VLIW execution must be identical to sequential execution.

Use the `vliwc` command-line tool to explore the machine architecture, parse programs, run them sequentially, and verify your optimized bundles:

```
vliwc --help
vliwc arch
vliwc parse /app/programs/single_hash.vasm
vliwc run /app/programs/single_hash.vasm
vliwc verify /app/programs/single_hash.vasm bundles.json
```

The tool and the format documentation embedded in it are the authoritative references for the machine model, assembly format, and bundle constraints.