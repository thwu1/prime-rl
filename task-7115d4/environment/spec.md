# ICFP Language Specification

An *Interstellar Communication Functional Program* (ICFP) consists of a list of space-separated *tokens*. A *token* consists of one or more printable ASCII characters, from ASCII code 33 (`!`) up to and including code 126 (`~`). There are 94 possible characters, and a *token* is a nonempty sequence of such characters.

The first character of a token is called the *indicator* and determines the type of the token. The (possibly empty) remainder of the token is called the *body*.

## Booleans

`indicator = T` with empty body represents the constant `true`.
`indicator = F` with empty body represents the constant `false`.

## Integers

`indicator = I`, requires a non-empty body.

The body is interpreted as a base-94 number. The digits are the 94 printable ASCII characters with `!` (ASCII 33) representing 0, `"` (ASCII 34) representing 1, `#` (ASCII 35) representing 2, and so on up to `~` (ASCII 126) representing 93.

Example: `I/6` represents the number 1337 (since `/` has value 14 and `6` has value 21, giving 14 * 94 + 21 = 1337).

## Strings

`indicator = S`

Characters in the body (ASCII codes 33 through 126) are translated to human-readable text using a substitution cipher. The mapping from position index (0 through 93) to human-readable character is:

```
abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!"#$%&'()*+,-./:;<=>?@[\]^_`|~ <LF>
```

The last two characters in this mapping are a single space (at position 92) and a single newline/linefeed (at position 93).

To decode a string token body: for each character `c` in the body, compute the index as `ord(c) - 33`, then look up that index in the mapping above.

Example: `SB%,,/` represents "Hello" because:
- `B` (ASCII 66) -> index 33 -> `H`
- `%` (ASCII 37) -> index 4 -> `e`
- `,` (ASCII 44) -> index 11 -> `l`
- `,` (ASCII 44) -> index 11 -> `l`
- `/` (ASCII 47) -> index 14 -> `o`

## Unary Operators

`indicator = U`, requires a body of exactly 1 character, followed by one ICFP expression (the operand).

| Body char | Meaning | Example |
|-----------|---------|---------|
| `-` | Integer negation | `U- I$` evaluates to -3 |
| `!` | Boolean not | `U! T` evaluates to false |
| `#` | String-to-int: encode each character of the string back into the token character set, then interpret as a base-94 number | `U# S4%34` evaluates to 15818151 |
| `$` | Int-to-string: express the integer in base-94, map each digit to a token character, then decode those characters as a string body | `U$ I4%34` evaluates to "test" |

## Binary Operators

`indicator = B`, requires a body of exactly 1 character, followed by two ICFP expressions (call them `x` and `y`).

| Body char | Meaning | Example |
|-----------|---------|---------|
| `+` | Integer addition | `B+ I# I$` -> 5 |
| `-` | Integer subtraction | `B- I$ I#` -> 1 |
| `*` | Integer multiplication | `B* I$ I#` -> 6 |
| `/` | Integer division (truncated towards zero) | `B/ U- I( I#` -> -3 |
| `%` | Integer modulo (consistent with truncated division) | `B% U- I( I#` -> -1 |
| `<` | Integer less-than comparison | `B< I$ I#` -> false |
| `>` | Integer greater-than comparison | `B> I$ I#` -> true |
| `=` | Equality comparison (works for int, bool, string) | `B= I$ I#` -> false |
| `\|` | Boolean or | `B\| T F` -> true |
| `&` | Boolean and | `B& T F` -> false |
| `.` | String concatenation | `B. S4% S34` -> "test" |
| `T` | Take: returns the first `x` characters of string `y` | `BT I$ S4%34` -> "tes" |
| `D` | Drop: returns string `y` with the first `x` characters removed | `BD I$ S4%34` -> "t" |
| `$` | Application: apply term `x` to `y` (see Lambda abstractions) | |

## Conditionals (If)

`indicator = ?` with an empty body, followed by three ICFP expressions. The first must evaluate to a boolean. If true, the second expression is evaluated and returned; otherwise the third.

Example: `? B> I# I$ S9%3 S./` evaluates to "no" (since 2 > 3 is false, the third expression `S./` = "no" is returned).

## Lambda Abstractions and Variables

`indicator = L` is a lambda abstraction. The body is interpreted as a base-94 number (same encoding as integers), which gives the variable number. It takes one ICFP expression as the function body.

`indicator = v` is a variable reference. The body is interpreted as a base-94 number giving the variable number.

When the first argument of the binary application operator `$` evaluates to a lambda abstraction, the second argument is assigned to that variable within the body. For example:

```
B$ B$ L# L$ v# B. SB%,,/ S}Q/2,$_ IK
```

represents (in more readable notation):

```
((lambda v2. lambda v3. v2) ("Hello" . " World!")) 42
```

which evaluates to the string "Hello World!" (v2 is bound to "Hello World!", v3 is bound to 42 but never used, so the result is v2).

## Evaluation Strategy

The language uses a **call-by-name** evaluation strategy:

1. The binary application operator `B$` is **non-strict**: the second argument is NOT evaluated before being passed to the function. Instead, it is substituted (using capture-avoiding substitution) in place of the binding variable throughout the function body.

2. If an argument is never referenced in the function body, it is never evaluated.

3. If a variable appears multiple times in the body, the substituted expression is evaluated independently each time.

All other built-in operators are **strict**: they fully evaluate their operands before applying the operation. Strict operators do not count as beta reductions.

### Evaluation example

```
B$ L# B$ L" B+ v" v" B* I$ I# v8
```

Step-by-step:
1. Apply lambda v2 to v8: substitute v2 with v8 in body (v2 is unused) -> `B$ L" B+ v" v" B* I$ I#`
2. Apply lambda v1 to `B* I$ I#`: substitute v1 with `B* I$ I#` -> `B+ B* I$ I# B* I$ I#`
3. Evaluate left operand: `B* I$ I#` = 3 * 2 = 6
4. Evaluate right operand: `B* I$ I#` = 3 * 2 = 6 (re-evaluated due to call-by-name)
5. `B+ I' I'` = 6 + 6 = 12

## Limits

Evaluation is aborted when exceeding 10,000,000 beta reductions (applications of `B$` where the first argument is a lambda). Built-in strict operators do not count toward this limit.
