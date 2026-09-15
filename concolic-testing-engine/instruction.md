Build `/app/bugfinder.py` that automatically discovers integer inputs triggering assertion failures in programs written in the WHILE3ADDR intermediate representation.

## Environment

- `/app/interpreter.py` — Parser and concrete interpreter for WHILE3ADDR programs. Exports `parse(source)` which returns a `Program` object, `execute(program, inputs)` which returns `(status, assertion_failed, env)`, and instruction AST classes (`ConstAssign`, `InputAssign`, `CopyAssign`, `BinOpAssign`, `CondGoto`, `Goto`, `Assert`, `Halt`). Also exports `OPS` and `RELOPS` dictionaries.
- `/app/programs/*.prog` — Target programs containing reachable assertion failures guarded by complex arithmetic constraints over `input()` variables. Random testing is infeasible due to the size of the integer input space.

## Requirements

Your `/app/bugfinder.py` must expose:

```python
def find_bug(program_path: str) -> list[int] | None
```

Takes the path to a `.prog` file and returns a list of integer inputs that trigger an assertion failure when fed to the concrete interpreter, or `None` if no failure is found. The returned inputs must cause `execute(parse(source), inputs)` to return `assertion_failed=True`.

The tool must work on arbitrary WHILE3ADDR programs — not just the provided examples. Target programs may have multiple input variables (up to 4+), arithmetic operations (both linear and nonlinear), conditional branches, loops, and deeply nested guard conditions.