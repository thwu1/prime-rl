`/app/` contains a stack-based virtual machine and analysis tools:

- `/app/vm` — Executes assembly programs. Supports additional modes for execution analysis (run `vm --help`).
- `/app/asmcheck` — Static analysis tool for assembly programs. Reports structural metrics, variable usage patterns, and potential issues (run `asmcheck --help`).
- `/app/spec.md` — VM instruction set documentation.

Five assembly programs in `/app/programs/` are functionally correct but contain pervasive redundancies that span multiple instructions and depend on inter-instruction relationships. The file `/app/targets.json` specifies each program's current static instruction count and the maximum allowed count after optimization.

Create `/app/optimizer.py` that reads an assembly file and outputs a semantically equivalent program with a reduced static instruction count:

```
python3 /app/optimizer.py <input.asm> <output.asm>
```

**Success criteria:**
- Each optimized program must produce byte-identical output to the original when run through `/app/vm` with any valid integer input
- Each optimized program's static instruction count must be at or below its target in `/app/targets.json`
- All optimized programs must be valid assembly parseable by the VM

Use the provided tools to analyze the programs, understand execution behavior, and verify correctness of your transformations. The programs vary in the nature and depth of their redundancies; some require careful analysis of variable relationships and control flow to optimize safely.

Example: `/app/vm /app/programs/prog1.asm < /app/inputs/p1.txt`