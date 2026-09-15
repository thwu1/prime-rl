A resilient LL parser for language "L" is implemented at `/app/src/lib.rs`, with a binary driver at `/app/src/main.rs` that reads stdin and prints a lossless Concrete Syntax Tree. The parser uses an event-based architecture with Open/Close/Advance markers to construct the CST, and a Pratt-style precedence climbing scheme for expression parsing. It currently supports functions, let/return statements, arithmetic/comparison/logical binary operators, unary operators, if/else, while, function calls, string literals, and line comments.

The language is being extended to "L2". The full grammar specification is at `/app/l2.ungrammar`. You must extend the parser to support these new constructs:

- **Array literals** (`[expr, expr, ...]`): comma-separated expressions within square brackets, including empty arrays and trailing commas.
- **Index expressions** (`expr[expr]`): postfix indexing with square brackets, chainable with function calls (e.g., `f()[0]`, `a[0][1]`, `a[0](x)`).
- **Ternary conditional** (`expr ? expr : expr`): the `?` `:` operator has the **lowest** precedence of all operators (below `||`), and is **right-associative** (i.e., `a ? b : c ? d : e` parses as `a ? b : (c ? d : e)`). It is NOT a standard binary operator and cannot be handled as one — the middle expression between `?` and `:` forms a distinct operand.
- **For-in loops** (`for name in expr block`): iterates a named variable over an iterable expression, followed by a block body. Like `if` and `while`, for-in is a block-carrying expression that does not require a trailing semicolon when used as a statement.

The extended parser must:

- Compile without errors or warnings via `cargo build --release` in `/app`.
- Produce correct CST output for all constructs defined in `/app/l2.ungrammar`.
- Preserve the lossless CST property: every source token must appear in the tree output.
- Remain resilient: never panic on malformed input, including incomplete arrays, missing ternary colons, and missing `in` keywords.
- Correctly implement the full seven-level precedence hierarchy specified in the grammar comments.
- Not break any existing parser functionality.