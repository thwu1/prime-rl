# SysY Language Specification

## 1. Grammar (EBNF)

Notation: `[x]` means x appears 0 or 1 times. `{x}` means x appears 0 or more times.
Terminal symbols are in double quotes or UPPERCASE. All others are non-terminals.

```
CompUnit      ::= {Decl | FuncDef}

Decl          ::= ConstDecl | VarDecl
ConstDecl     ::= "const" "int" ConstDef {"," ConstDef} ";"
ConstDef      ::= IDENT {"[" ConstExp "]"} "=" ConstInitVal
ConstInitVal  ::= ConstExp | "{" [ConstInitVal {"," ConstInitVal}] "}"
VarDecl       ::= "int" VarDef {"," VarDef} ";"
VarDef        ::= IDENT {"[" ConstExp "]"} ["=" InitVal]
InitVal       ::= Exp | "{" [InitVal {"," InitVal}] "}"

FuncDef       ::= FuncType IDENT "(" [FuncFParams] ")" Block
FuncType      ::= "void" | "int"
FuncFParams   ::= FuncFParam {"," FuncFParam}
FuncFParam    ::= "int" IDENT ["[" "]" {"[" ConstExp "]"}]

Block         ::= "{" {BlockItem} "}"
BlockItem     ::= Decl | Stmt
Stmt          ::= LVal "=" Exp ";"
               | [Exp] ";"
               | Block
               | "if" "(" Exp ")" Stmt ["else" Stmt]
               | "while" "(" Exp ")" Stmt
               | "break" ";"
               | "continue" ";"
               | "return" [Exp] ";"

Exp           ::= LOrExp
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
ConstExp      ::= Exp
```

## 2. Lexical Elements

### Identifiers
```
IDENT ::= [a-zA-Z_][a-zA-Z0-9_]*
```
Identifiers cannot be keywords.

### Integer Literals
```
INT_CONST ::= decimal | octal | hexadecimal
decimal     ::= [1-9][0-9]* | "0"
octal       ::= "0" [0-7]+
hexadecimal ::= "0" ("x"|"X") [0-9a-fA-F]+
```

### Keywords
`const`, `int`, `void`, `if`, `else`, `while`, `break`, `continue`, `return`

### Operators (by precedence, lowest to highest)
1. `||` — logical OR (left-associative, short-circuit)
2. `&&` — logical AND (left-associative, short-circuit)
3. `==` `!=` — equality (left-associative)
4. `<` `>` `<=` `>=` — relational (left-associative)
5. `+` `-` — additive (left-associative)
6. `*` `/` `%` — multiplicative (left-associative)
7. `+` `-` `!` — unary (prefix, right-associative)

### Delimiters
`(` `)` `[` `]` `{` `}` `;` `,`

### Comments
- Single-line: `// ...` (to end of line)
- Multi-line: `/* ... */`

## 3. Type System

The only data type is `int` (32-bit signed integer, range -2^31 to 2^31-1).
All expressions evaluate to `int`.
In boolean contexts (`if`, `while`, `&&`, `||`, `!`): 0 is false, non-zero is true.
Boolean operators `&&`, `||`, `!`, and comparison operators produce 0 or 1.

## 4. Scoping Rules

- Each `Block` (`{...}`) introduces a new scope.
- Variables declared in a block are local to that block and its nested blocks.
- A variable in an inner block **shadows** any variable with the same name in outer blocks.
- When a block ends, its local variables are destroyed.
- Global variables and functions are declared at the top level (outside any function).
- Functions can access global variables (unless shadowed by a local).
- Function parameters are local to the function body.

## 5. Variable Initialization

- **Global variables** without explicit initializer default to 0.
- **Global arrays** without explicit initializer have all elements defaulting to 0.
- **Local variables** without explicit initializer have **undefined** values.
- **Partial array initialization**: if fewer initializers are provided than the array size, remaining elements are initialized to 0. Example: `int a[5] = {1, 2, 3};` gives `a = {1, 2, 3, 0, 0}`.
- **`const` variables** must have compile-time-evaluable initializers. All identifiers in a `ConstExp` must refer to previously declared constants.

## 6. Arrays

- Array dimensions must be constant expressions (evaluable at compile time).
- Multi-dimensional arrays use **row-major** layout. For `int a[M][N]`, element `a[i][j]` is at flat index `i * N + j`.
- Arrays are passed to functions by reference. When a function parameter is `int arr[]` or `int arr[][N]`, the first dimension is omitted (the array is passed as a pointer).

## 7. Short-Circuit Evaluation

- `&&` (logical AND): If the left operand evaluates to 0 (false), the right operand is **not evaluated**, and the result is 0.
- `||` (logical OR): If the left operand evaluates to non-zero (true), the right operand is **not evaluated**, and the result is 1.

## 8. Integer Arithmetic

- Division `/` truncates toward zero (same as C99). Examples: `7/2 = 3`, `-7/2 = -3`.
- Modulo `%` satisfies `a == (a/b)*b + (a%b)`. Examples: `7%2 = 1`, `-7%2 = -1`.
- Overflow wraps around in 32-bit two's complement.

## 9. Functions

- A valid program must contain exactly one `main` function with signature `int main()`.
- `main` takes no parameters and returns `int`.
- A `void` function may use `return;` (no value) or fall off the end.
- An `int` function must return a value on all paths (behavior is undefined otherwise).
- Functions must be defined before they are called (no forward declarations).

## 10. Control Flow

- `if-else`: The `else` clause binds to the nearest unmatched `if` (dangling else rule).
- `while`: Standard loop. Condition is evaluated before each iteration.
- `break`: Exits the innermost enclosing `while` loop.
- `continue`: Skips to the next iteration of the innermost enclosing `while` loop.
