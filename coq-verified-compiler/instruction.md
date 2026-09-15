A Coq project at `/app/` implements a verified compiler for a simple arithmetic expression language. The project consists of:

- `Syntax.v` — expression AST (constants, addition, subtraction, multiplication)
- `Semantics.v` — denotational semantics via an `eval` function
- `StackMachine.v` — a stack machine with an `exec` function and a compositionality lemma `exec_app`
- `Compiler.v` — a compiler from expressions to stack-machine code with a correctness theorem `compile_correct`
- `Optimizer.v` — a constant-folding optimization pass with a preservation theorem `optimize_correct`
- `Tests.v` — computational tests that verify concrete evaluations via `reflexivity`
- `_CoqProject` — build configuration

The project is broken in multiple ways. There are bugs in the implementation, incomplete proofs (`Admitted`), and build configuration errors. Your goal is to make the entire project build successfully with `make`, with no `Admitted` proofs remaining and all computational tests in `Tests.v` passing.

Bugs and issues are present in the build configuration, in the stack machine execution semantics, and in the optimizer's constant folding logic. The `exec_app`, `compile_correct`, and `optimize_correct` proofs all need to be completed.