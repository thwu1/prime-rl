The Monkey programming language implementation at `/app/` includes a complete lexer, parser, AST, bytecode compiler, and stack-based virtual machine (based on "Writing A Compiler In Go" by Thorsten Ball). The language currently relies entirely on recursion for iteration — it has no loop constructs.

Implement `while` loops with `break` and `continue` statements that work through the **bytecode compiler and VM execution path**.

## Syntax

```
while (<condition>) { <body> }
break;
continue;
```

`while` is an expression that evaluates to `null` when the loop terminates (matching how `if` without `else` evaluates to `null`). `break` exits the innermost enclosing while loop. `continue` jumps to the next iteration of the innermost enclosing while loop. Both are statements.

## Constraints

- `while`, `break`, and `continue` must be recognized as keywords
- The compiler must emit correct bytecode for while loops using jump instructions (`OpJump`, `OpJumpNotTruthy`, `OpNull`, etc.)
- Nested while loops must work correctly with `break`/`continue` affecting only the innermost loop
- While loops must work inside functions (local variable scope) and with closures
- `break`/`continue` inside nested `if` expressions within loops must work correctly
- Postfix increment/decrement operators (`x++`, `x--`) must function correctly inside while loop bodies — verify correctness across all variable scopes, nesting levels, and when variables are re-initialized each iteration via `let` inside a loop. The existing postfix operator implementation has latent bugs that only surface when loops are present.
- All existing tests (`go test ./...`) must continue to pass

Verification tests are pre-installed at `/app/vm/while_loop_test.go`.