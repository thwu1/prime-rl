# Cool Lexer Token Specification

## Overview

The `cool_lexer` binary reads a Cool source file and writes one JSON object per line to stdout. Each object represents a token.

## JSON Output Format

### Tokens without values
```json
{"type": "<TOKEN_TYPE>", "line": <line_number>}
```

### Tokens with values
```json
{"type": "<TOKEN_TYPE>", "value": <value>, "line": <line_number>}
```

The `value` field type depends on the token: string for `INT_CONST`, `STR_CONST`, `TYPEID`, `OBJECTID`, `ERROR`; JSON boolean for `BOOL_CONST`.

## Token Types

### Keywords (case-insensitive)

All Cool keywords are case-insensitive. Emit the uppercase name:

| Token | Pattern |
|-------|---------|
| `CLASS` | `class`, `CLASS`, `Class`, etc. |
| `ELSE` | `else` |
| `FI` | `fi` |
| `IF` | `if` |
| `IN` | `in` |
| `INHERITS` | `inherits` |
| `LET` | `let` |
| `LOOP` | `loop` |
| `POOL` | `pool` |
| `THEN` | `then` |
| `WHILE` | `while` |
| `CASE` | `case` |
| `ESAC` | `esac` |
| `OF` | `of` |
| `NEW` | `new` |
| `ISVOID` | `isvoid` |
| `NOT` | `not` |

Keywords have no `value` field.

### Multi-character Operators

| Token | Symbol |
|-------|--------|
| `DARROW` | `=>` |
| `ASSIGN` | `<-` |
| `LE` | `<=` |

No `value` field.

### Boolean Constants

`BOOL_CONST` — The first letter of `true`/`false` **must be lowercase**; remaining letters are case-insensitive. `True` and `FALSE` starting with uppercase are type/object identifiers, not booleans.

```json
{"type": "BOOL_CONST", "value": true, "line": 3}
{"type": "BOOL_CONST", "value": false, "line": 4}
```

### Integer Constants

`INT_CONST` — One or more digits. Value is the digit string.

```json
{"type": "INT_CONST", "value": "42", "line": 5}
```

### String Constants

`STR_CONST` — Text between double quotes, with escape sequences processed. Value is the escape-processed string content (JSON-escaped in output).

Escape sequences: `\n` → newline, `\t` → tab, `\b` → backspace, `\f` → formfeed, `\\` → backslash, `\"` → double quote, `\<newline>` → newline (backslash at end of line), `\<other>` → the character itself.

Maximum string length: 1024 characters.

```json
{"type": "STR_CONST", "value": "hello\nworld", "line": 6}
```

### Identifiers

| Token | Pattern | Example |
|-------|---------|---------|
| `TYPEID` | Starts with uppercase letter, followed by letters/digits/underscores | `Main`, `SELF_TYPE`, `IO` |
| `OBJECTID` | Starts with lowercase letter, followed by letters/digits/underscores | `main`, `self`, `foo_bar` |

```json
{"type": "TYPEID", "value": "Main", "line": 1}
{"type": "OBJECTID", "value": "self", "line": 2}
```

### Single-character Tokens

Use the character itself as the `type`. No `value` field:

`{` `}` `(` `)` `;` `:` `.` `,` `@` `~` `+` `-` `*` `/` `<` `=`

```json
{"type": "{", "line": 1}
{"type": "+", "line": 3}
```

### Error Tokens

`ERROR` — Emitted for lexical errors. `value` is a descriptive message:

- `"EOF in comment"` — unterminated block comment at end of file
- `"EOF in string constant"` — unterminated string at end of file
- `"Unterminated string constant"` — unescaped newline in string
- `"String contains null character"` — null byte in string
- `"String constant too long"` — string exceeds 1024 characters
- `"Unmatched *)"` — closing comment delimiter without matching open
- For unrecognized characters: the character itself

## Comments

- Single-line: `--` to end of line (not tokenized)
- Block: `(* ... *)`, may be **nested** (not tokenized)

## Flex Implementation Notes

Use `%option noyywrap` and `%option yylineno` for automatic line tracking. Use Flex start conditions (`%x`) for nested comment, single-line comment, and string constant states. Each token action should print its JSON line to stdout without returning a value (Flex continues scanning automatically). Include `"json_escape.h"` in the `%{` block for the `json_print_escaped(FILE*, const char*, int)` helper. The provided `lex_main.c` handles file opening and calling `yylex()`.
