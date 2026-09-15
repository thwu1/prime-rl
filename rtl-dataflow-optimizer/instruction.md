Implement `/app/optimizer.py` exporting `optimize(prog: dict) -> dict` -- a semantics-preserving optimizer for RTL (Register Transfer Language) programs.

The RTL format and interpreter are defined in `/app/rtl.py`. Eight programs are in `/app/programs/`: `poly_eval`, `const_arith`, `dead_triangle`, `branch_const`, `cascade`, `loop_constprop`, `nested_diamond`, `strength_chain`. Use `rtl.load_program(path)` to load them and `rtl.interpret(prog, args)` to execute them.

## Semantic Preservation

For any structurally valid RTL program P and any inputs, `interpret(optimize(P), args)` must equal `interpret(P, args)`. This is verified against:

- All eight provided programs with multiple known test inputs per program.
- Extended input ranges: `cascade` over x in [-5,10), y in [-3,5); `strength_chain` over x in [-50,51); `nested_diamond` over x in [-10,11), y in [-5,6).
- 40 randomly generated valid RTL programs (12 nodes, 2 params each), each tested with 15 random inputs. The optimizer must not crash or produce incorrect results on any structurally valid program.
- Varied inputs per program to ensure no crashes on edge cases.

## Optimization Quality

A "computation op" is any reachable instruction with `kind == "op"` whose `op` is not `const` or `move` (i.e., arithmetic/logic operations like `add`, `sub`, `mul`, etc.). "Reachable" means traversable from the entrypoint via successor edges.

Each provided program contains redundancies. The optimizer must achieve at least the following minimum reductions in computation op count (original minus optimized):

| Program | Min Reduction |
|---|---|
| poly_eval | 2 |
| const_arith | 3 |
| dead_triangle | 3 |
| cascade | 3 |
| loop_constprop | 1 |
| nested_diamond | 2 |
| strength_chain | 3 |

Additionally:
- `const_arith` must have at most 3 computation ops after optimization.
- `dead_triangle` must have at most 2 computation ops after optimization.
- `branch_const`: node 19 (the false branch of its constant conditional) must become unreachable after optimization.
- `poly_eval`: at most 1 `add(r1, r2)` instruction may remain in reachable code (the original has 3).
- `loop_constprop`: at most 2 `add(r3, r4)` instructions may remain in reachable code (the original has 3).

## Structural Validity

Optimized programs must retain `name`, `params`, `entrypoint`, and `code` fields. The entrypoint must reference a node in `code`, and all successor references from reachable instructions must point to valid nodes.

## Build Artifacts

Create `/app/Makefile` with:

- `optimize`: runs the optimizer on all eight programs, writing optimized RTL JSON to `/app/optimized/<name>.json`. Each output file must be loadable via `rtl.load_program()` and contain valid `code` and `entrypoint` fields.
- `render`: generates before/after Graphviz CFG visualizations as SVG files at `/app/cfg_output/<name>_before.svg` and `/app/cfg_output/<name>_after.svg` for each program. Each SVG file must contain a valid `<svg` tag. Graphviz (`dot`) is pre-installed.