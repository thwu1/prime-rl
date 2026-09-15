# CFG File Format

A context-free grammar (CFG) file has the following structure, read line by line:

1. A line containing the number of terminal symbols
2. One line per terminal symbol (one symbol per line)
3. A line containing the number of nonterminal symbols
4. One line per nonterminal symbol (one symbol per line)
5. A line containing the start symbol (must be one of the listed nonterminals)
6. A line containing the number of productions
7. One line per production: the left-hand side nonterminal followed by zero or more right-hand side symbols, all separated by single spaces

A production with an empty right-hand side (epsilon production) consists of only the left-hand side nonterminal on its line, with no symbols following it.

## Augmented Grammar Convention

The grammar is augmented: the **first production** (production 0) expands the start symbol into a sequence that begins with the terminal `BOF` and ends with the terminal `EOF`. These are terminal symbols representing the beginning and end of the input stream. Input token sequences provided for parsing always start with `BOF` and end with `EOF`.

## Example

```
7
BOF
EOF
+
*
(
)
id
4
S
E
T
F
S
7
S BOF E EOF
E E + T
E T
T T * F
T F
F ( E )
F id
```

This defines:
- 7 terminals: `BOF`, `EOF`, `+`, `*`, `(`, `)`, `id`
- 4 nonterminals: `S`, `E`, `T`, `F`
- Start symbol: `S`
- 7 productions (0-indexed):
  - 0: S → BOF E EOF
  - 1: E → E + T
  - 2: E → T
  - 3: T → T * F
  - 4: T → F
  - 5: F → ( E )
  - 6: F → id

## Input Token File Format

An input file contains a sequence of terminal symbols separated by whitespace (spaces or newlines). The sequence always begins with `BOF` and ends with `EOF`.
