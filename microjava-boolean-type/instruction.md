A complete MicroJava compiler (scanner, parser, symbol table, code generator) and stack-based VM are at `/app/`. The compiler is a single-pass recursive descent compiler written in Java. Modify it to fully support a `boolean` data type.

## Required features

The modified compiler must handle all of the following:

- A predeclared `boolean` type with constants `true` (value 1) and `false` (value 0)
- Boolean variable declarations: `boolean b;`
- Storing comparison results in boolean variables: `b = a > 5;`
- Compound boolean expressions with short-circuit `&&` and `||` in assignments: `b = x > 0 && y > 0;`
- Boolean variables used directly as conditions: `if (b) ...`, `while (b) ...`
- Boolean variables mixed with comparisons in compound conditions: `if (b || x > 0) ...`
- Parenthesized boolean sub-expressions: `if ((a == 0 || b == 0) && c > 0) ...`
- Printing boolean values via `print`: `print(b)` outputs `1` or `0`
- Boolean method parameters: `void foo(boolean b) { if (b) ... }`
- Boolean method return values: `boolean bar(int x) { return x > 0; }`

## Verification

Two test programs at `/app/BooleanTest.mj` and `/app/BoolMethodTest.mj` must compile and run correctly:

```
cd /app && javac MJ/Compiler.java
java MJ.Compiler BooleanTest.mj && java MJ.Run BooleanTest.obj
java MJ.Compiler BoolMethodTest.mj && java MJ.Run BoolMethodTest.obj
```

## Compiler source layout

- `/app/MJ/Scanner.java` — lexical analyzer
- `/app/MJ/Parser.java` — recursive descent parser with integrated code generation
- `/app/MJ/Token.java` — token representation
- `/app/MJ/Compiler.java` — driver
- `/app/MJ/Run.java` — VM interpreter
- `/app/MJ/SymTab/` — symbol table (`Obj.java`, `Struct.java`, `Scope.java`, `Tab.java`)
- `/app/MJ/CodeGen/` — code generation (`Code.java`, `Operand.java`, `Label.java`, `Decoder.java`)