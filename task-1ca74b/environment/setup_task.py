#!/usr/bin/env python3
"""Setup script: creates /app/spec/, /app/programs/, and /app/lib/ for the SysY→LLVM IR task."""
import os

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)

# ============================================================
# SysY Language Specification
# ============================================================

SYSY_SPEC = r"""# SysY Language Specification

SysY is a subset of C used in the Chinese National Compiler Design Competition.
A SysY program is a single source file containing global declarations and function
definitions. There must be exactly one `int main()` function (no parameters, returns int).

## EBNF Grammar

```
CompUnit      ::= [CompUnit] (Decl | FuncDef);
Decl          ::= ConstDecl | VarDecl;
ConstDecl     ::= "const" BType ConstDef {"," ConstDef} ";";
BType         ::= "int";
ConstDef      ::= IDENT {"[" ConstExp "]"} "=" ConstInitVal;
ConstInitVal  ::= ConstExp | "{" [ConstInitVal {"," ConstInitVal}] "}";
VarDecl       ::= BType VarDef {"," VarDef} ";";
VarDef        ::= IDENT {"[" ConstExp "]"}
                | IDENT {"[" ConstExp "]"} "=" InitVal;
InitVal       ::= Exp | "{" [InitVal {"," InitVal}] "}";
FuncDef       ::= FuncType IDENT "(" [FuncFParams] ")" Block;
FuncType      ::= "void" | "int";
FuncFParams   ::= FuncFParam {"," FuncFParam};
FuncFParam    ::= BType IDENT ["[" "]" {"[" ConstExp "]"}];
Block         ::= "{" {BlockItem} "}";
BlockItem     ::= Decl | Stmt;
Stmt          ::= LVal "=" Exp ";"
                | [Exp] ";"
                | Block
                | "if" "(" Exp ")" Stmt ["else" Stmt]
                | "while" "(" Exp ")" Stmt
                | "break" ";"
                | "continue" ";"
                | "return" [Exp] ";";
Exp           ::= LOrExp;
LVal          ::= IDENT {"[" Exp "]"};
PrimaryExp    ::= "(" Exp ")" | LVal | Number;
Number        ::= INT_CONST;
UnaryExp      ::= PrimaryExp | IDENT "(" [FuncRParams] ")" | UnaryOp UnaryExp;
UnaryOp       ::= "+" | "-" | "!";
FuncRParams   ::= Exp {"," Exp};
MulExp        ::= UnaryExp | MulExp ("*" | "/" | "%") UnaryExp;
AddExp        ::= MulExp | AddExp ("+" | "-") MulExp;
RelExp        ::= AddExp | RelExp ("<" | ">" | "<=" | ">=") AddExp;
EqExp         ::= RelExp | EqExp ("==" | "!=") RelExp;
LAndExp       ::= EqExp | LAndExp "&&" EqExp;
LOrExp        ::= LAndExp | LOrExp "||" LAndExp;
ConstExp      ::= Exp;
```

## Tokens

### Identifiers
Letter or underscore followed by letters, digits, or underscores.

### Integer Constants
- Decimal: non-zero digit followed by digits (e.g., `42`)
- Octal: `0` followed by octal digits 0-7 (e.g., `010` = 8)
- Hexadecimal: `0x` or `0X` followed by hex digits (e.g., `0x1F` = 31)
- `0` alone is zero.

### Comments
- Single-line: `//` to end of line
- Multi-line: `/*` to first `*/`

### Keywords
`int`, `void`, `const`, `if`, `else`, `while`, `break`, `continue`, `return`

### Operators (by precedence, low to high)
1. `||` (logical OR, left-to-right)
2. `&&` (logical AND, left-to-right)
3. `==` `!=` (equality, left-to-right)
4. `<` `>` `<=` `>=` (relational, left-to-right)
5. `+` `-` (additive, left-to-right)
6. `*` `/` `%` (multiplicative, left-to-right)
7. `+` `-` `!` (unary, right-to-left)

## Type System
- Only type is `int` (32-bit signed integer).
- Arrays can be multi-dimensional: `int a[3][4]`.
- In boolean contexts, 0 is false, non-zero is true.
- `&&` and `||` return 0 or 1.
- Relational and equality operators return 0 or 1.
- Integer division truncates toward zero: `(-7)/2 == -3`.
- `%` follows: `a % b == a - (a/b)*b`.

## Scoping Rules
- Global declarations are visible from point of declaration to end of file.
- Each `{ }` block creates a new scope.
- Inner scope declarations shadow outer declarations of the same name.
- A function's parameters are in a scope enclosing the function body block.
- Functions can only be defined at the top level.
- Function scope sees only global scope (lexical scoping).

## Array Initialization
Arrays use C-style brace initialization:
1. `{}` initializes all elements to 0.
2. A braced initializer `{...}` at depth d fills one sub-array of dimension d.
3. Scalar (non-braced) elements fill positions sequentially within the current sub-array.
4. When a braced group appears, it aligns to the start of the next sub-array.
5. Missing initializers are filled with 0.

## Global Variables
- Uninitialized global variables (and arrays) are initialized to 0.
- Global initializers must be constant expressions.

## Local Variables
- Uninitialized local variables have undefined values (treat as 0 for safety).
- Local initializers can use any expression valid in the current scope.

## Constants
- `const` variables must have an initializer.
- `const` values must be computable at compile time.

## Functions
- Return type is `int` or `void`.
- Scalar parameters are passed by value.
- Array parameters are passed by reference.
- You can pass a sub-array: if `int a[4][3]`, then `a[1]` is valid for `int param[]`.

## Short-Circuit Evaluation
- `&&`: if left operand is 0, right operand is NOT evaluated. Result is 0 or 1.
- `||`: if left operand is non-zero, right operand is NOT evaluated. Result is 0 or 1.

## Control Flow
- `break`: exits innermost `while` loop.
- `continue`: jumps to condition check of innermost `while` loop.
- `return`: exits current function, optionally with a value.

## Runtime Library
| Function | Signature | Behavior |
|----------|-----------|----------|
| `getint` | `int getint()` | Read one integer from stdin |
| `getch` | `int getch()` | Read one char, return ASCII |
| `getarray` | `int getarray(int a[])` | Read n, then n ints into a[]; return n |
| `putint` | `void putint(int a)` | Print integer (no newline) |
| `putch` | `void putch(int a)` | Print char |
| `putarray` | `void putarray(int n, int a[])` | Print "n: a[0] a[1] ... a[n-1]\n" |
"""

# ============================================================
# LLVM IR Reference Notes
# ============================================================

LLVMIR_NOTES = r"""# LLVM IR Quick Reference

These notes cover the subset of LLVM IR relevant to targeting SysY code generation.
LLVM IR is a typed, SSA-based intermediate representation.

## Module Structure

A `.ll` file contains declarations and definitions. No target triple or data layout
is required for basic compilation with `clang`.

## Types

- `i1` -- boolean (1-bit integer)
- `i32` -- 32-bit signed integer
- `[N x T]` -- array of N elements of type T, e.g., `[5 x i32]`, `[3 x [4 x i32]]`
- `ptr` -- opaque pointer (LLVM 15+; replaces typed pointers like `i32*`)
- `void` -- no value (for function return types)

## Global Variables

```llvm
@x = global i32 0
@arr = global [3 x i32] [i32 1, i32 2, i32 3]
@mat = global [2 x [3 x i32]] [[3 x i32] [i32 1, i32 2, i32 3], [3 x i32] zeroinitializer]
@z = global [5 x i32] zeroinitializer
```

## Functions

```llvm
define i32 @add(i32 %a, i32 %b) {
entry:
  %sum = add i32 %a, %b
  ret i32 %sum
}

define void @nop() {
entry:
  ret void
}

declare void @putint(i32)          ; external function declaration
```

Every basic block must end with exactly one terminator instruction (`ret`, `br`).
The first basic block is the entry block (label `entry:` by convention).

## Instructions

### Memory Operations

```llvm
%p = alloca i32                      ; allocate stack space for one i32
%p = alloca [5 x i32]                ; allocate stack space for array
store i32 %val, ptr %p               ; write value to memory
%v = load i32, ptr %p                ; read value from memory
store ptr %q, ptr %pp                ; store a pointer
%q = load ptr, ptr %pp               ; load a pointer
```

### getelementptr (GEP)

Computes addresses within aggregate types. Does NOT access memory.

```llvm
; For a local array: %arr = alloca [5 x i32]
; Access element at index %i:
%elem_ptr = getelementptr [5 x i32], ptr %arr, i32 0, i32 %i

; For a 2D array: %mat = alloca [3 x [4 x i32]]
; Access element [%r][%c]:
%elem_ptr = getelementptr [3 x [4 x i32]], ptr %mat, i32 0, i32 %r, i32 %c

; Pointer arithmetic (for array-parameter access, base type i32):
%next = getelementptr i32, ptr %base, i32 %offset
```

The first index after `ptr` selects "which instance" of the aggregate (0 for stack
variables and globals). Subsequent indices index into the aggregate's dimensions.

### Arithmetic

```llvm
%r = add i32 %a, %b
%r = sub i32 %a, %b
%r = mul i32 %a, %b
%r = sdiv i32 %a, %b                ; signed division, truncates toward zero
%r = srem i32 %a, %b                ; signed remainder: a - (a sdiv b) * b
```

### Comparison

All produce `i1` results.

```llvm
%c = icmp eq i32 %a, %b             ; equal
%c = icmp ne i32 %a, %b             ; not equal
%c = icmp slt i32 %a, %b            ; signed less than
%c = icmp sgt i32 %a, %b            ; signed greater than
%c = icmp sle i32 %a, %b            ; signed less-or-equal
%c = icmp sge i32 %a, %b            ; signed greater-or-equal
```

### Type Conversion

```llvm
%r = zext i1 %flag to i32           ; zero-extend i1 to i32 (0 or 1)
```

### Control Flow

```llvm
br label %target                     ; unconditional branch
br i1 %cond, label %iftrue, label %iffalse  ; conditional branch
ret i32 %val                         ; return value from function
ret void                             ; return from void function
```

### Function Calls

```llvm
%r = call i32 @func(i32 %x, ptr %arr)  ; call returning i32
call void @proc(i32 %x)                ; void call
```

## SSA Form

Each virtual register (`%name`) is assigned exactly once (Static Single Assignment).
The simplest strategy for code generation: use `alloca` for every variable, then
`load`/`store` to read/write. This avoids the need for `phi` nodes. LLVM's `mem2reg`
pass can later promote allocas to SSA registers if optimization is desired.

## Array Parameters

SysY array parameters (`int a[]`) become `ptr` in LLVM IR. The callee uses
`getelementptr i32, ptr %param, i32 %idx` for element access. The caller passes
the array's base address (for local arrays, this is the alloca pointer; for
sub-arrays like `a[1]` of `int a[3][4]`, use GEP to get the sub-array address).

## Debugging Tools

```bash
clang program.ll runtime.c -o program    # compile IR + C runtime to executable
llvm-as program.ll -o program.bc         # validate IR syntax (assembles to bitcode)
opt -S --verify program.ll -o /dev/null  # verify IR is well-formed
lli program.ll                           # interpret IR directly (limited)
```
"""

# ============================================================
# AST Specification
# ============================================================

AST_SPEC = r"""# AST Format

The parser (`/app/parser.py`) produces an AST as a list of Python tuples.

## Usage

```python
import sys; sys.path.insert(0, '/app')
from parser import Lexer, Parser

with open('input.sy') as f:
    source = f.read()
toks = Lexer(source).tokenize()
ast = Parser(toks).parse()
# ast is a list of top-level declarations
```

## Node Types

### Top-Level Declarations

**Function definition:**
`('fdef', return_type, name, params, body)`
- `return_type`: `'int'` or `'void'`
- `name`: string
- `params`: list of `('par', name, dims)` where dims is None for scalar, or list for array param
  - For array params, dims[0] is always None (unsized first dimension), remaining are const exprs
- `body`: `('blk', [items])`

**Variable declaration:**
`('vdecl', [vdefs])`
- Each vdef: `('vdef', name, dims, init_or_None)`
- `dims`: list of dimension expressions (empty list `[]` for scalar)
- `init`: `('iexp', expr)` for scalar init, `('ilist', [init_vals])` for array init, or None

**Const declaration:**
`('cdecl', [cdefs])`
- Each cdef: `('cdef', name, dims, init)`
- Same structure as vdef but init is always present

### Statements

- `('blk', [items])` -- Block `{ ... }`
- `('asgn', lval_expr, value_expr)` -- Assignment
- `('estmt', expr)` -- Expression statement
- `('if', cond, then_stmt, else_stmt_or_None)` -- If/else
- `('whl', cond, body_stmt)` -- While loop
- `('brk',)` -- Break
- `('cont',)` -- Continue
- `('ret', expr_or_None)` -- Return
- `('empty',)` -- Empty statement (`;`)

### Expressions

- `('num', int_value)` -- Integer literal
- `('lv', name, [index_exprs])` -- L-value / variable / array access
- `('bop', op, left, right)` -- Binary op: `+`,`-`,`*`,`/`,`%`,`<`,`>`,`<=`,`>=`,`==`,`!=`,`&&`,`||`
- `('uop', op, operand)` -- Unary op: `+`,`-`,`!`
- `('call', name, [arg_exprs])` -- Function call

### Key Details

- Array dimensions in declarations (`dims`) are expression AST nodes, not integers.
  They must be evaluated (they're always constant expressions per the SysY spec).
- An lvalue `('lv', name, [])` with empty index list is a bare variable reference.
  If the variable is an array, this gives the array reference (for passing to functions).
- `('lv', name, [idx1, idx2])` represents `name[idx1][idx2]`.
- Assignment target is always an `('lv', ...)` node.
- `('asgn', ('lv', 'x', []), ('num', 5))` represents `x = 5;`
"""

# ============================================================
# SysY Runtime Library (C source)
# ============================================================

RUNTIME_C = r"""#include <stdio.h>

int getint(void) {
    int t;
    scanf("%d", &t);
    return t;
}

int getch(void) {
    return getchar();
}

int getarray(int a[]) {
    int n;
    scanf("%d", &n);
    for (int i = 0; i < n; i++) {
        scanf("%d", &a[i]);
    }
    return n;
}

void putint(int a) {
    printf("%d", a);
}

void putch(int a) {
    printf("%c", a);
}

void putarray(int n, int a[]) {
    printf("%d:", n);
    for (int i = 0; i < n; i++) {
        printf(" %d", a[i]);
    }
    printf("\n");
}
"""

# ============================================================
# Test Programs
# ============================================================

PROGRAMS = {
    '01_basic_return': r"""int main() {
    return 42;
}
""",

    '02_arithmetic': r"""int main() {
    int a = 3 + 4 * 2;
    int b = (3 + 4) * 2;
    int c = 10 / 3;
    int d = 10 % 3;
    putint(a); putch(32);
    putint(b); putch(32);
    putint(c); putch(32);
    putint(d); putch(10);
    return 0;
}
""",

    '03_if_else': r"""int main() {
    int a = 5;
    if (a > 3) {
        putint(1);
    } else {
        putint(0);
    }
    putch(32);
    if (a < 3) {
        putint(1);
    } else {
        putint(0);
    }
    putch(32);
    if (a == 5) {
        putint(1);
    }
    putch(10);
    return 0;
}
""",

    '04_while_loop': r"""int main() {
    int i = 0;
    int sum = 0;
    while (i < 10) {
        sum = sum + i;
        i = i + 1;
    }
    putint(sum);
    putch(10);
    return 0;
}
""",

    '05_fibonacci': r"""int fib(int n) {
    if (n <= 1) return n;
    return fib(n - 1) + fib(n - 2);
}

int main() {
    putint(fib(10));
    putch(10);
    return 0;
}
""",

    '06_arrays_1d': r"""int main() {
    int a[5] = {10, 20, 30, 40, 50};
    int sum = 0;
    int i = 0;
    while (i < 5) {
        sum = sum + a[i];
        i = i + 1;
    }
    putint(sum);
    putch(10);
    return 0;
}
""",

    '07_void_func': r"""void print_sum(int a, int b) {
    putint(a + b);
    putch(10);
}

int add(int a, int b) {
    return a + b;
}

int main() {
    print_sum(3, 4);
    int result = add(10, 20);
    putint(result);
    putch(10);
    return 0;
}
""",

    '08_neg_division': r"""int main() {
    int a = -7 / 2;
    int b = -13 / 4;
    int c = 7 / -2;
    int d = -15 / 4;
    putint(a); putch(32);
    putint(b); putch(32);
    putint(c); putch(32);
    putint(d); putch(10);
    return 0;
}
""",

    '09_neg_modulo': r"""int main() {
    int a = -7 % 3;
    int b = 7 % -3;
    int c = -13 % 5;
    int d = -1 % 7;
    putint(a); putch(32);
    putint(b); putch(32);
    putint(c); putch(32);
    putint(d); putch(10);
    return 0;
}
""",

    '10_short_circuit': r"""int counter = 0;

int inc() {
    counter = counter + 1;
    return counter;
}

int main() {
    if (0 && inc()) {}
    putint(counter); putch(10);
    if (1 || inc()) {}
    putint(counter); putch(10);
    if (1 && inc()) {}
    putint(counter); putch(10);
    if (0 || inc()) {}
    putint(counter); putch(10);
    return 0;
}
""",

    '11_array_modify': r"""void fill_squares(int arr[], int n) {
    int i = 0;
    while (i < n) {
        arr[i] = i * i;
        i = i + 1;
    }
}

int main() {
    int a[5] = {0, 0, 0, 0, 0};
    fill_squares(a, 5);
    int sum = 0;
    int i = 0;
    while (i < 5) {
        sum = sum + a[i];
        i = i + 1;
    }
    putint(sum); putch(10);
    return 0;
}
""",

    '12_scoping_blocks': r"""int main() {
    int x = 10;
    int y = 100;
    {
        int x = 20;
        putint(x); putch(32);
        {
            int x = 30;
            y = 200;
            putint(x); putch(32);
        }
        putint(x); putch(32);
    }
    putint(x); putch(32);
    putint(y); putch(10);
    return 0;
}
""",

    '13_break_continue': r"""int main() {
    int i = 0;
    int sum = 0;
    while (i < 20) {
        i = i + 1;
        if (i % 3 == 0) continue;
        if (i > 10) break;
        sum = sum + i;
    }
    putint(sum);
    putch(10);
    return 0;
}
""",

    '14_multi_dim_array': r"""int main() {
    int a[2][3] = {{1, 2, 3}, {4, 5, 6}};
    putint(a[0][0]); putch(32);
    putint(a[0][2]); putch(32);
    putint(a[1][1]); putch(10);
    return 0;
}
""",

    '15_const_decl': r"""int main() {
    const int N = 5;
    const int M = N * 3;
    putint(M); putch(32);
    const int arr[3] = {10, 20, 30};
    int sum = arr[0] + arr[1] + arr[2];
    putint(sum); putch(10);
    return 0;
}
""",

    '16_complex_init': r"""int main() {
    int a[2][3] = {1, 2, 3, 4, 5, 6};
    putint(a[0][0]); putch(32);
    putint(a[0][2]); putch(32);
    putint(a[1][0]); putch(32);
    putint(a[1][2]); putch(10);
    return 0;
}
""",

    '17_nested_calls': r"""int fact(int n) {
    if (n <= 1) return 1;
    return n * fact(n - 1);
}

int main() {
    putint(fact(5));
    putch(10);
    return 0;
}
""",

    '18_global_array': r"""int g[5];
int i;

void fill() {
    i = 0;
    while (i < 5) {
        g[i] = i * i;
        i = i + 1;
    }
}

int main() {
    fill();
    int j = 0;
    while (j < 5) {
        if (j > 0) putch(32);
        putint(g[j]);
        j = j + 1;
    }
    putch(10);
    return 0;
}
""",
}

# ============================================================
# Write files
# ============================================================

def main():
    write_file('/app/spec/sysy_spec.md', SYSY_SPEC)
    write_file('/app/spec/llvmir_notes.md', LLVMIR_NOTES)
    write_file('/app/spec/ast_spec.md', AST_SPEC)
    write_file('/app/lib/sysy_runtime.c', RUNTIME_C)

    for name, source in PROGRAMS.items():
        write_file(f'/app/programs/{name}/program.sy', source)

if __name__ == '__main__':
    main()
