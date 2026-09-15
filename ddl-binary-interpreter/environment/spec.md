# DaeDaLus DDL Subset Specification

This document specifies the subset of the DaeDaLus parser specification language that your transpiler must support. DaeDaLus is a domain-specific language for formally specifying binary data formats and generating parsers from those specifications.

## Source Files

- Files use `.ddl` extension and contain only ASCII
- Line comments: `--` to end of line
- Block comments: `{- ... -}` (nestable)

## Declarations

```
def Name = body
```

Each source file defines one or more named parsers. The entry point is always `Main`. Declarations are top-level and order-independent (forward references are allowed).

## Naming Convention

- Names starting with uppercase are parsers (e.g., `UInt8`, `DataChunk`)
- Names starting with lowercase are values/variables (e.g., `len`, `tag`)

## Primitive Parsers

| Parser | Description |
|--------|-------------|
| `UInt8` | Read 1 byte, return as unsigned integer |
| `BEUInt16` | Read 2 bytes big-endian, return as unsigned integer |
| `BEUInt32` | Read 4 bytes big-endian, return as unsigned integer |
| `LEUInt16` | Read 2 bytes little-endian, return as unsigned integer |
| `LEUInt32` | Read 4 bytes little-endian, return as unsigned integer |
| `Match [b1, b2, ...]` | Match exact byte sequence (hex `0x..` or decimal) |
| `Match "string"` | Match exact ASCII string |
| `END` | Succeed only at end of input (or sub-stream) |

## Block Sequencing

```
block
  field1 = Parser1      -- named field (appears in output)
  let x = Parser2       -- local binding (NOT in output)
  $$ = Parser3          -- explicit result (block returns this value)
  @Parser4              -- execute but discard result
  Parser5               -- execute for side effect (e.g., Match, END)
```

A block executes statements in order. The result is:
- If `$$` is used: the value bound to `$$`
- Otherwise: a JSON object with all named fields

Local bindings (`let`) are available to subsequent statements but do not appear in the output.

## Biased Choice

```
P <| Q
```

Try parser `P` first. If `P` fails, **backtrack** (restore input position) and try `Q`. Both must be attempted from the same input position.

## Tagged Unions (First)

```
First
  tag1 = Parser1
  tag2 = Parser2
```

Try each alternative in order with backtracking. The result is a JSON object `{"tagN": value}` for the first alternative that succeeds.

## Tagged Values

```
{| tag_name = Parser |}
```

Parse with the given parser and wrap the result as `{"tag_name": value}`.

## Repetition

| Form | Description |
|------|-------------|
| `Many P` | Zero or more (greedy, stops on failure with backtracking) |
| `Many N P` | Exactly N times (N is integer literal or variable) |

For unbounded `Many`, each iteration saves the input position before attempting `P`. On failure, the position is restored and repetition stops (returning all successful results).

## Case Expressions

```
case expr of
  1 -> Parser1
  2 -> Parser2
  _ -> DefaultParser
```

Evaluate `expr`, match against patterns. Patterns are integer literals or `_` (wildcard). The matched branch's parser is executed.

## Sub-stream Parsing (Chunk)

```
Chunk N Parser
```

Create a bounded sub-stream of exactly `N` bytes from the current position. Run `Parser` on that sub-stream. Advance the parent stream by `N` bytes regardless. `END` inside the sub-stream checks the sub-stream's boundary, not the parent's.

## Guard

```
Guard (condition)
```

Evaluate the boolean condition. If false, the parse **fails** (triggers backtracking if inside a choice). If true, succeeds with no value.

## Type Coercions

```
expr as uint 64
expr as? SomeType
```

For this interpreter, type coercions are identity operations (no-op). They exist in the language for type-checking purposes. Parse the inner expression normally and return its value unchanged.

## Expressions

The following expression forms appear in Guards, case discriminants, and `Many` count arguments:

- **Integer literals**: decimal (`42`) or hexadecimal (`0x2A`)
- **Variables**: lowercase identifiers referring to `let` bindings or named fields from the enclosing block
- **Field access**: `x.field` accesses a named field of a struct value
- **Arithmetic**: `+`, `-`, `*`
- **Comparison**: `==`, `!=`, `<`, `<=`, `>`, `>=`
- **Boolean**: comparison results are used by Guards

## Output Format

The generated parser must output a JSON representation of the parsed data to stdout:

- `UInt8`, `BEUInt16`, etc. → JSON integer
- `Match` → `null` (consumed but no output)
- `END` → `null`
- `Guard` → `null`
- Block with named fields → JSON object `{"field1": v1, "field2": v2, ...}`
- Block with `$$` → the value of `$$`
- `Many` → JSON array
- `First` / `{| tag = ... |}` → JSON object `{"tag": value}`
- `case` → result of matched branch

## Error Handling

On parse failure (unexpected byte, insufficient input, guard failure with no backtracking option), the generated parser must exit with a non-zero status code.
