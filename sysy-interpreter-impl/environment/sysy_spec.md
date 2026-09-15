# SysY Language Specification

SysY is a subset of C used in Chinese national compiler design competitions. This document defines its syntax and semantics.

## 1. Grammar (EBNF)

Notation: `[X]` means X appears 0 or 1 times. `{X}` means X appears 0 or more times. Terminal symbols are in double quotes or UPPERCASE.

```
CompUnit      ::= {CompUnit} (Decl | FuncDef);

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

## 2. Lexical Elements

### 2.1 Identifiers

An identifier starts with a letter or underscore, followed by letters, digits, or underscores.

### 2.2 Integer Constants

Three forms are supported:
- **Decimal**: a non-zero digit followed by digits (e.g., `42`, `100`)
- **Octal**: a `0` followed by octal digits 0-7 (e.g., `017` = 15, `0377` = 255)
- **Hexadecimal**: `0x` or `0X` followed by hex digits (e.g., `0x1F` = 31, `0XFF` = 255)

Range: [0, 2^31 - 1]. The literal itself does not include a sign.

### 2.3 Comments

- Single-line: `//` to end of line
- Multi-line: `/*` to the next `*/`

### 2.4 Keywords

`const`, `int`, `void`, `if`, `else`, `while`, `break`, `continue`, `return`

### 2.5 Operators and Punctuation

`+` `-` `*` `/` `%` `<` `>` `<=` `>=` `==` `!=` `&&` `||` `!` `=` `(` `)` `[` `]` `{` `}` `;` `,`

## 3. Semantic Rules

### 3.1 Compilation Unit

A SysY program is a single source file consisting of global declarations and function definitions. There must be exactly one function named `main` with return type `int` and no parameters. `main` is the program entry point.

Top-level identifiers (variables, constants, functions) must not be redefined. Their scope extends from the point of declaration to end of file.

### 3.2 Types

The only base type is `int` (32-bit signed integer). Arrays of `int` (including multi-dimensional) are supported. No floats, pointers, structs, or strings.

### 3.3 Constants

Constants declared with `const` must be initializable at compile time. All expressions in a constant initializer must themselves be constant expressions (using only literal values and previously declared constants).

### 3.4 Variables

Local variables without explicit initialization have undefined values. Global variables without explicit initialization are zero-initialized (including all array elements).

### 3.5 Array Declaration and Initialization

Arrays are declared with explicit dimension sizes (which must be constant expressions evaluating to non-negative integers):

```
int a[3][4];        // 3x4 array
const int N = 5;
int b[N];           // dimension from const
```

Array initialization follows C-style brace-elision rules:

1. `{}` initializes all elements to zero.
2. A brace-enclosed sub-list initializes the corresponding sub-aggregate. Unspecified trailing elements are zero.
3. Non-braced scalars fill elements sequentially within the current sub-aggregate.

Examples for `int a[4][2]`:
- `{1, 2, 3, 4, 5, 6, 7, 8}` → `{{1,2}, {3,4}, {5,6}, {7,8}}`
- `{{1, 2}, {3, 4}, 5, 6, 7, 8}` → `{{1,2}, {3,4}, {5,6}, {7,8}}`
- `{1, 2, {3}, {5}, 7, 8}` → `{{1,2}, {3,0}, {5,0}, {7,8}}`
- `{{}, {3, 4}, 5, 6}` → `{{0,0}, {3,4}, {5,6}, {0,0}}`

### 3.6 Functions

- `int` functions should return a value via `return Exp;`. If control reaches the end without a return, the return value is undefined.
- `void` functions may only use `return;` (no expression).
- Parameters are passed by value for `int`, by reference for arrays.
- Array parameters have the first dimension omitted: `int arr[]` or `int mat[][N]`.

### 3.7 Scoping

- Each `Block` (`{...}`) creates a new scope.
- Inner declarations shadow outer ones with the same name.
- A variable's scope extends from its declaration to the end of the enclosing block.

### 3.8 Expressions

All expressions evaluate to `int`. In boolean contexts (if/while conditions), 0 is false, non-zero is true.

Operator precedence (lowest to highest):
1. `||` (logical OR) — left-to-right
2. `&&` (logical AND) — left-to-right
3. `==` `!=` — left-to-right
4. `<` `>` `<=` `>=` — left-to-right
5. `+` `-` — left-to-right
6. `*` `/` `%` — left-to-right
7. `+` `-` `!` (unary) — right-to-left

**Short-circuit evaluation**: `||` and `&&` use short-circuit semantics. For `a || b`, if `a` is non-zero, `b` is not evaluated (result is 1). For `a && b`, if `a` is zero, `b` is not evaluated (result is 0).

**Integer division**: truncates toward zero (C99 semantics). `-7 / 2 == -3`, `-7 % 2 == -1`, `7 / -2 == -3`, `7 % -2 == 1`.

**Logical NOT**: `!0 == 1`, `!nonzero == 0`.

### 3.9 Statements

- Assignment: `LVal = Exp;` — the left side must be a variable (not a constant).
- If/else: dangling else binds to the nearest if.
- While: `while (Exp) Stmt` — evaluates condition before each iteration.
- Break/continue: only valid inside while loops.
- Return: exits the current function with the given value (or no value for void functions).

### 3.10 Control flow: break and continue

`break` exits the innermost enclosing while loop. `continue` skips the rest of the current iteration and re-evaluates the while condition.

## 4. Runtime Library

The following functions are available without any `#include` directive:

| Function | Signature | Description |
|---|---|---|
| `getint` | `int getint()` | Read one integer from stdin |
| `getch` | `int getch()` | Read one character from stdin, return its ASCII value |
| `getarray` | `int getarray(int a[])` | Read n, then n integers into a[]; return n |
| `putint` | `void putint(int a)` | Print integer a (no newline) |
| `putch` | `void putch(int a)` | Print character with ASCII value a |
| `putarray` | `void putarray(int n, int a[])` | Print `n:` then n space-separated elements of a, then newline |

`putarray` output format: `printf("%d:", n); for(i=0;i<n;i++) printf(" %d", a[i]); printf("\n");`

## 5. Program Execution

The program starts by executing `main()`. The process exit code is `main()`'s return value modulo 256.
