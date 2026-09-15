The file `/app/compile.rkt` contains an incomplete compiler that transforms programs in a Scheme-like language (R5) into x86-64 assembly. Many of its transformation functions contain `'todo` stubs or placeholder comments where implementations should go.

R5 programs use integers, booleans, arithmetic (`+`, `-`, `*`), comparisons (`eq?`, `<`, `<=`, `>`, `>=`), conditionals (`if`), `let`-bindings, `while` loops, mutation (`set!`), heap-allocated vectors (`make-vector`, `vector-ref`, `vector-set!`), top-level function definitions (`define`), function application, and lambda expressions with lexical closures.

Only `/app/compile.rkt` needs modification. Other `.rkt` and `.c` files in `/app/` are part of the supporting infrastructure and should not be changed.

To compile and run a program:

```
cd /app
racket main.rkt /app/test-programs/prog.scm
./output
```

Programs that call `(read)` take input from stdin; sample inputs are in `/app/input-files/`.

Your goal: complete `/app/compile.rkt` so that every test program in `/app/test-programs/` compiles to a correct x86-64 binary that produces the expected output when run.