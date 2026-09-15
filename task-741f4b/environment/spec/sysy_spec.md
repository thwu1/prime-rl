# SysY Language Specification

## 1. Lexical Elements

### 1.1 Keywords
```
const  int  void  if  else  while  break  continue  return
```

### 1.2 Identifiers
```
IDENT ::= [a-zA-Z_][a-zA-Z0-9_]*
```
Identifiers are case-sensitive. Keywords cannot be used as identifiers.

### 1.3 Integer Constants
```
INT_CONST ::= decimal-const | octal-const | hex-const
decimal-const ::= [1-9][0-9]*  |  0
octal-const   ::= 0[0-7]+
hex-const     ::= 0[xX][0-9a-fA-F]+
```

### 1.4 Operators and Delimiters
```
+  -  *  /  %           Arithmetic
<  >  <=  >=  ==  !=    Relational
&&  ||  !               Logical
=                       Assignment
(  )  [  ]  {  }        Grouping
;  ,                    Punctuation
```

### 1.5 Comments
```
// single-line comment (to end of line)
/* multi-line comment (does not nest) */
```

### 1.6 Whitespace
Spaces, tabs, carriage returns, and newlines are ignored except as token separators.

---

## 2. Grammar (EBNF)

```ebnf
CompUnit      ::= {Decl | FuncDef}

Decl          ::= ConstDecl | VarDecl
ConstDecl     ::= "const" BType ConstDef {"," ConstDef} ";"
BType         ::= "int"
ConstDef      ::= IDENT {"[" ConstExp "]"} "=" ConstInitVal
ConstInitVal  ::= ConstExp | "{" [ConstInitVal {"," ConstInitVal}] "}"
VarDecl       ::= BType VarDef {"," VarDef} ";"
VarDef        ::= IDENT {"[" ConstExp "]"}
                | IDENT {"[" ConstExp "]"} "=" InitVal
InitVal       ::= Exp | "{" [InitVal {"," InitVal}] "}"

FuncDef       ::= FuncType IDENT "(" [FuncFParams] ")" Block
FuncType      ::= "void" | "int"
FuncFParams   ::= FuncFParam {"," FuncFParam}
FuncFParam    ::= BType IDENT ["[" "]" {"[" ConstExp "]"}]

Block         ::= "{" {BlockItem} "}"
BlockItem     ::= Decl | Stmt
Stmt          ::= LVal "=" Exp ";"
                | [Exp] ";"
                | Block
                | "if" "(" Cond ")" Stmt ["else" Stmt]
                | "while" "(" Cond ")" Stmt
                | "break" ";"
                | "continue" ";"
                | "return" [Exp] ";"

Exp           ::= AddExp
Cond          ::= LOrExp
LVal          ::= IDENT {"[" Exp "]"}
PrimaryExp    ::= "(" Exp ")" | LVal | Number
Number        ::= INT_CONST
UnaryExp      ::= PrimaryExp
                | IDENT "(" [FuncRParams] ")"
                | UnaryOp UnaryExp
UnaryOp       ::= "+" | "-" | "!"
FuncRParams   ::= Exp {"," Exp}
MulExp        ::= UnaryExp | MulExp ("*" | "/" | "%") UnaryExp
AddExp        ::= MulExp | AddExp ("+" | "-") MulExp
RelExp        ::= AddExp | RelExp ("<" | ">" | "<=" | ">=") AddExp
EqExp         ::= RelExp | EqExp ("==" | "!=") RelExp
LAndExp       ::= EqExp | LAndExp "&&" EqExp
LOrExp        ::= LAndExp | LOrExp "||" LAndExp
ConstExp      ::= AddExp
```

---

## 3. Semantics

### 3.1 Types
SysY has only one data type: **int** (32-bit signed integer). Arrays of int are supported with arbitrary dimensions.

### 3.2 Operator Precedence (highest to lowest)
| Precedence | Operators        | Associativity |
|------------|------------------|---------------|
| 1          | `!` `+` `-` (unary) | Right       |
| 2          | `*` `/` `%`      | Left          |
| 3          | `+` `-` (binary) | Left          |
| 4          | `<` `>` `<=` `>=`| Left          |
| 5          | `==` `!=`        | Left          |
| 6          | `&&`             | Left          |
| 7          | `||`             | Left          |

### 3.3 Integer Arithmetic
- Division and modulo truncate toward zero (C99 semantics):
  - `-17 / 5 == -3`, `-17 % 5 == -2`
  - `17 / -5 == -3`, `17 % -5 == 2`
- Relational and equality operators return 1 (true) or 0 (false).
- Logical NOT `!` returns 1 for zero operand, 0 for non-zero.

### 3.4 Short-Circuit Evaluation
- `&&`: If the left operand is 0, the right operand is **not** evaluated; result is 0.
- `||`: If the left operand is non-zero, the right operand is **not** evaluated; result is 1.
- When evaluated, `&&` yields 1 if both operands are non-zero, else 0.
- When evaluated, `||` yields 1 if either operand is non-zero, else 0.

### 3.5 Variables and Scoping
- **Global variables**: declared at file scope, visible throughout the file, zero-initialized by default.
- **Local variables**: declared in blocks, visible from declaration to end of enclosing block.
- **Shadowing**: a local declaration of name `x` shadows any outer `x` for the duration of the enclosing block.
- **`const`**: the value (or all elements for arrays) must be a compile-time constant.
- **ConstExp**: expressions used for array dimensions and const initializers must be evaluable at compile time (they may reference previously declared constants and integer literals).

### 3.6 Arrays
- Declared with dimensions that must be compile-time constants: `int a[3][4]`
- Stored in row-major order.
- **Initialization**: `int a[2][3] = {{1,2,3},{4,5,6}}` fills elements in order. Partial initialization fills remaining elements with 0. `int a[5] = {1,2}` gives `{1,2,0,0,0}`. Flat initialization is allowed: `int a[2][3] = {1,2,3,4,5,6}`.
- **Global arrays**: all elements zero-initialized if no initializer.
- **Indexing**: `a[i][j]` for multi-dimensional arrays.

### 3.7 Functions
- Two return types: `int` and `void`.
- Parameters: `int` passed by value; arrays passed by reference.
- Array parameters: first dimension is unspecified (`int a[]`), subsequent dimensions must be constants (`int a[][3]`).
- The program must contain exactly one function named `main` with return type `int` and no parameters.
- Recursion is supported.
- A function reaching its closing `}` without a `return` statement: returns 0 for `int` functions.

### 3.8 Control Flow
- **if/else**: the `else` clause binds to the nearest unmatched `if` (dangling else rule).
- **while**: standard loop. `break` exits the innermost loop. `continue` skips to the next iteration of the innermost loop.
- **return**: exits the current function. `return expr;` for int functions, `return;` for void functions.

---

## 4. Runtime Library

The following functions are available without declaration:

```c
int getint();              // Read one integer from stdin (whitespace-delimited)
int getch();               // Read one character from stdin, return its ASCII value
int getarray(int a[]);     // Read n, then n integers into a[]; return n

void putint(int a);        // Print integer a to stdout (no trailing newline)
void putch(int a);         // Print character with ASCII value a to stdout
void putarray(int n, int a[]);  // Print "n: a[0] a[1] ... a[n-1]\n" to stdout
```

### putarray format detail
`putarray(n, a)` outputs exactly: the decimal value of n, then a colon, then for each element a space followed by the decimal value, then a newline. Example: `putarray(3, a)` where `a={10,20,30}` outputs `3: 10 20 30\n`.

### getarray detail
`getarray(a)` reads an integer n from stdin, then reads n integers into `a[0]` through `a[n-1]`, and returns n.

---

## 5. Program Execution

1. Global variable declarations and function definitions are processed in order of appearance.
2. Execution begins by calling `main()`.
3. The return value of `main()` becomes the program's exit code (modulo 256).
