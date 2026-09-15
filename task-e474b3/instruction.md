A liblouis braille translation table at `/app/tables/sci-notation.ctb` defines character mappings for letters, digits, punctuation, and mathematical operators, but contains no translation rules. Design and implement all translation rules required so that `lou_translate -f unicode.dis,/app/tables/sci-notation.ctb` correctly renders scientific and mathematical text in Unicode braille.

You must evaluate the available liblouis opcodes (documented in `/app/docs/opcodes.txt`) and select the appropriate ones for each behavior below. Many opcodes have overlapping functionality but differ in word-boundary semantics, numeric-context handling, or pass-ordering behavior. Choosing the wrong opcode will produce subtly incorrect output in edge cases.

## Required Behaviors

**Function contractions:** The names `sin`, `cos`, `tan`, `log`, and `exp` each contract to a prefix indicator (dots 5) followed by the function's first letter. This must happen only when the name stands alone as a word — never when embedded inside words like `since`, `basin`, `cosine`, `tangent`, or `explore`. Punctuation (e.g., parentheses) constitutes a word boundary, so `sin(x)` must still contract.

**Decimal and number formatting:** A period between digits is a decimal point (dots 46, not the punctuation dots 256). A leading decimal such as `.5` must also produce the decimal dot pattern preceded by a number sign — this is a distinct behavior from mid-number decimals and requires a different opcode. Commas between digits are thousands separators, keeping the digit sequence under one number sign.

**Superscript/subscript notation:** A caret before one or more digits becomes a superscript indicator (dots 35). An underscore before one or more digits becomes a subscript indicator (dots 16). Only the caret or underscore is consumed — the following digit(s) must be preserved and translated normally. Before non-digit characters, caret and underscore retain their default representations (dots 45 and 456). These rules operate during the first translation pass on input characters and require a specific opcode prefix to exclude them from back-translation.

**Multi-pass expression cleanup:** A second translation pass removes the redundant number sign (dots 3456) that appears after arithmetic operators (`+`, `-`, `=`) and after superscript/subscript indicators. Only the number sign must be removed — the preceding operator or indicator must be preserved. Pass2 rules operate on dot patterns (the output of pass1), so matched patterns must reflect what pass1 actually produced, not the original input characters' default representations.

## Constraints

- The completed table must pass `lou_checktable` validation.
- Append rules to the existing table — do not modify or remove character definitions.
- Context and multipass opcodes have a mandatory prefix requirement documented in the opcode reference.

## Tools

- `lou_translate -f unicode.dis,/app/tables/sci-notation.ctb` — forward-translate text
- `lou_trace -f unicode.dis,/app/tables/sci-notation.ctb` — trace rule application
- `lou_checktable /app/tables/sci-notation.ctb` — validate table syntax
- Opcode reference: `/app/docs/opcodes.txt`