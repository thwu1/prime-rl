A partial compiler pipeline for a micro-Decaf language is provided at `/app/`. The pipeline translates `.dcf` source through a flex/bison frontend (`scanner.l`, `parser.y`) into three-address code (TAC) IR, then applies Python-based optimization and CFG visualization. The pipeline is broken and incomplete.

## Problems to solve

**Parser repair.** `make` in `/app/` fails. The scanner and parser sources contain build errors and the parser mishandles operator precedence/associativity (e.g., `10 - 3 - 2` must yield 5, not 9). Fix the sources so `./decaf2tac` builds and correctly compiles sample programs in `/app/sample_programs/`.

**Dataflow optimizer.** `/app/optimizer.py` is a stub. Implement the exported function `optimize(func_list) -> func_list` with these passes iterated to a fixed point: constant propagation and folding, dead code elimination (liveness analysis), common subexpression elimination (available expressions), and unreachable code elimination. The optimizer must preserve program semantics while removing redundancy. Unary operations on constants must also be folded. Side-effecting instructions (CALL, PRINT) must never be eliminated. CSE must be invalidated when operand variables are redefined.

**CFG visualization.** `/app/dot_output.py` is a stub. Implement `cfg_to_dot(func) -> str` producing valid Graphviz DOT for the function's control-flow graph. Each reachable basic block becomes a box node (`B<id>`) labeled with its instructions; edges represent successor relationships. Output must pass `dot -Tsvg` validation.

## TAC IR format

```
FUNC <name>:                     # function entry
  <var> = <var> <op> <var>       # binary op (+, -, *, /, %, ==, !=, <, >, <=, >=, &&, ||)
  <var> = <op> <var>             # unary op (-, !)
  <var> = <var>                  # copy
  <var> = <literal>              # constant load (integers, true, false)
  <var> = CALL <name> <args...>  # function call
  PARAM <var>                    # parameter declaration
  LABEL <label>                  # label
  GOTO <label>                   # unconditional jump
  IF <var> GOTO <label>          # conditional branch (nonzero)
  IFFALSE <var> GOTO <label>     # conditional branch (zero)
  RETURN <var>                   # return with value
  RETURN                         # void return
  PRINT <var>                    # output
END FUNC                         # function end
```

## Pipeline

`.dcf` source -> `./decaf2tac` -> TAC text -> `python3 main.py [--dot DIR]` -> optimized TAC + DOT files

## Provided files

- `/app/scanner.l`, `/app/parser.y`, `/app/Makefile` — flex/bison frontend (broken)
- `/app/tac_parser.py` — Python TAC parser (working)
- `/app/cfg.py` — CFG builder from TAC (working)
- `/app/main.py` — optimizer driver (working)
- `/app/optimizer.py`, `/app/dot_output.py` — stubs to complete
- `/app/sample_programs/` — micro-Decaf test programs