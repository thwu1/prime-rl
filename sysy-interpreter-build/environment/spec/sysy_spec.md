# SysY Language Specification

## Grammar (EBNF)

Notation: `[...]` = 0 or 1 repetitions, `{...}` = 0 or more repetitions. Terminals are in double quotes or UPPERCASE.

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
`IDENT` starts with a letter or underscore, followed by letters, digits, or underscores.

### Integer Literals
- Decimal: nonzero digit followed by digits (e.g. `42`)
- Octal: `0` followed by octal digits 0-7 (e.g. `077` = 63)
- Hexadecimal: `0x` or `0X` followed by hex digits (e.g. `0xFF` = 255)
- Just `0` is decimal zero.
- Range: [0, 2^31 - 1]

### Comments
- Line comment: `//` to end of line
- Block comment: `/*` to `*/`

### Keywords
`int`, `void`, `const`, `if`, `else`, `while`, `break`, `continue`, `return`

## Semantic Rules

### Compilation Unit
- A program must contain exactly one `main` function: `int main()`.
- Top-level identifiers (variables, constants, functions) must be unique.
- Scope of a declaration extends from the declaration to end of file.

### Variables and Constants
- `const` values must be evaluable at compile time.
- Array dimensions must be constant non-negative integers.
- Uninitialized global variables and uninitialized array elements default to 0.
- Uninitialized local variables have undefined values.

### Array Initialization
Arrays may be initialized with mixed braced and unbraced values:
- `{}` initializes all elements to zero
- A braced group `{...}` fills one sub-array at the current dimension
- Bare (unbraced) values fill sequentially into the current sub-array
- Missing values at any level are implicitly zero

Example for `int a[4][2]`:
- `{1, 2, {3}, {5}, 7, 8}` produces `{{1,2}, {3,0}, {5,0}, {7,8}}`
  - `1, 2` are bare values filling `a[0]` = `{1, 2}`
  - `{3}` fills `a[1]` = `{3, 0}` (implicit zero)
  - `{5}` fills `a[2]` = `{5, 0}`
  - `7, 8` are bare values filling `a[3]` = `{7, 8}`

### Functions
- `int` functions should return a value on all paths (undefined if missing).
- `void` functions may only use bare `return;`.
- `int` parameters are passed by value.
- Array parameters are passed by reference. First dimension is unspecified (`[]`), subsequent dimensions have constant sizes.
- A sub-array can be passed: if `int a[4][3]`, then `a[1]` (type `int[3]`) can be passed to `int param[]`.

### Scoping
- Block `{...}` creates a new scope.
- Inner declarations shadow outer ones with the same name.
- Global and local variable scopes can overlap; local takes precedence.
- Variable names may shadow function names.

### Expressions
- All expressions are `int` type.
- In conditionals (`if`/`while`), 0 is false, nonzero is true.
- `||` returns 1 if either operand is nonzero, 0 otherwise. Short-circuit: right operand not evaluated if left is nonzero.
- `&&` returns 1 if both operands are nonzero, 0 otherwise. Short-circuit: right operand not evaluated if left is zero.
- Operator precedence (lowest to highest): `||`, `&&`, `==`/`!=`, `<`/`>`/`<=`/`>=`, `+`/`-`, `*`/`/`/`%`, unary `+`/`-`/`!`
- Integer division truncates toward zero (C semantics).
- `if` with dangling `else` follows nearest-match rule.

## Runtime Library

These functions are built-in (no `#include` needed):

| Function | Signature | Description |
|---|---|---|
| `getint` | `int getint()` | Read one integer from stdin |
| `getch` | `int getch()` | Read one character from stdin, return as int |
| `getarray` | `int getarray(int a[])` | Read n, then n ints into array a; return n |
| `putint` | `void putint(int a)` | Print integer (no newline) |
| `putch` | `void putch(int a)` | Print character (e.g. `putch(10)` prints newline) |
| `putarray` | `void putarray(int n, int a[])` | Print `"n: a[0] a[1] ... a[n-1]\n"` |
