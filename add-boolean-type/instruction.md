A complete MicroJava compiler is at `/app/Compiler/`. It compiles MicroJava source (`.mj`) to stack-based bytecode (`.obj`) and executes it on a virtual machine. The compiler consists of a Scanner (`MJ/Scanner.java`), Parser (`MJ/Parser.java`), Symbol Table (`MJ/SymTab/`), and Code Generator (`MJ/CodeGen/`). The VM is in `MJ/Run.java`.

Extend the compiler to support a `boolean` data type. Currently MicroJava only supports `int`, `char`, array, and class types. After modification, all of the following must work:

- **Type and constants**: `boolean` is a predeclared type (like `int`/`char`). `true` and `false` are predeclared constants of type `boolean` with internal values 1 and 0.

- **Variables and assignment**: Boolean variables store `true`/`false` or the result of comparisons and boolean expressions: `boolean b; b = true; b = a > 5; b = x > 3 && y < 20;`

- **Conditions**: Boolean variables work directly in `if`/`while` conditions: `if (b) { ... }` and `while (running) { ... }`

- **General boolean expressions**: `||` and `&&` must work in any expression context (not only in conditions), including parenthesized compound expressions: `b = (a == 0 || a == 1) && c > 0;`

- **Print**: `print(b)` outputs 1 or 0.

- **Method return**: Methods may return `boolean`: `boolean isPositive(int x) { return x > 0; }`

- **Backward compatibility**: Existing MicroJava programs that do not use booleans must continue to compile and run correctly.

Compile: `cd /app/Compiler && javac MJ/Compiler.java MJ/Run.java MJ/Decode.java`
Run: `java -cp /app/Compiler MJ.Compiler program.mj && java -cp /app/Compiler MJ.Run program.obj`

A sample program `/app/Compiler/Eratos.mj` demonstrates existing features and must continue to work after modification.