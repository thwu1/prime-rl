`/app/ir.py` defines a three-address code IR with two register classes: GP (12 physical registers `r0`–`r11`) and XMM (14 physical registers `xmm0`–`xmm13`). Programs at `/app/programs/*.json` contain functions whose virtual registers must be mapped to physical registers or stack slots.

Implement `/app/allocator.py` exposing:

```python
def allocate(func: ir.Function) -> dict:
```

returning a dict that maps every virtual register name in `func.vreg_classes` to a physical register of the correct class or a stack slot (`"stack_0"`, `"stack_1"`, …).

## Validity

- No two virtual registers that are simultaneously live at any program point may share a physical register.
- GP vregs must map to GP physicals or stack slots; XMM vregs to XMM physicals or stack slots.

## Quality Bounds

- Programs whose peak register demand within a class does not exceed k must produce zero spills for that class.
- `force_spill`: at most 1 spill.
- `spill_cascade`: at most 4 GP spills and at most 2 XMM spills.
- `briggs_coalesce`: every `copy` instruction's source and destination must be allocated to the same physical register (zero remaining moves).
- `nested_loop_pressure`: zero spills.

## Environment

Not all test IR programs are pre-built. `/app/tools/gen_stress_ir.c` is a C program that generates additional ones (`spill_cascade`, `nested_loop_pressure`). See the `Makefile` for build targets. `/app/tools/check_alloc.py` validates allocations from the command line. `jq` is available for JSON inspection.