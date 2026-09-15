The MicroJava compiler at `/app/Compiler/` is a complete single-pass recursive-descent compiler targeting a stack-based virtual machine. Source is in `MJ/` with sub-packages `SymTab/` and `CodeGen/`. Build with `javac MJ/*.java MJ/SymTab/*.java MJ/CodeGen/*.java` from `/app/Compiler/`. Compile programs with `java MJ.Compiler prog.mj`, run with `java MJ.Run prog.obj`.

Extend the compiler with two new language features:

## 1. Boolean Data Type

Add `boolean` as a predeclared type with predeclared constants `true` and `false`. Boolean variables occupy one word (same as `int`). The extended language must support:

- Variable declarations: `boolean flag;`
- Assignment from boolean expressions: `flag = a < b;`
- Compound boolean expressions using `&&` (and) and `||` (or) with short-circuit evaluation: `flag = a < b && b < c;`
- Parenthesized sub-expressions: `flag = (a < b || a == c) && b < d;`
- Boolean variables usable directly in conditions: `if (flag) ...`, `while (flag) ...`
- Printing boolean values with `print` (outputs `1` for true, `0` for false)

## 2. Enumeration Types

Add enum type declarations and enum constant access:

```
enum Color {RED, GREEN, BLUE}
Color c;
c = Color.RED;
if (c == Color.BLUE) ...
print(c, 0);
```

Enum constants behave as integer values starting from 0 in declaration order. Enum variables can be declared, assigned, compared, and printed.

## Verification

The test programs at `/app/test_programs/` must compile without errors and produce the expected output when run on the MicroJava VM. Each `.mj` file has a corresponding `.expected` file containing the expected program output (excluding the VM's timing message).