# rex — Extended Regular Expression Analyzer

## Expression Syntax

| Syntax    | Meaning                                        |
|-----------|-------------------------------------------------|
| `a`-`z`   | Character literal                               |
| `@`       | Epsilon (empty string)                          |
| `#`       | Empty set (no strings)                          |
| `r1 \| r2`| Union (alternation)                             |
| `r1 r2`   | Concatenation (juxtaposition)                   |
| `r*`      | Kleene star (postfix, zero or more repetitions) |
| `~r`      | Complement (prefix): all strings NOT in L(r)    |
| `r1 & r2` | Intersection                                    |
| `( r )`   | Grouping                                        |

### Operator Precedence (highest to lowest)

1. `*` (postfix)
2. `~` (prefix)
3. Concatenation (juxtaposition)
4. `&` (intersection)
5. `|` (union)

All binary operators are left-associative.

## Subcommands

### `rex match EXPR STRING`

Print `true` if STRING is in L(EXPR), `false` otherwise.

### `rex empty EXPR ALPHABET`

Print `true` if L(EXPR) = {} over the given alphabet, `false` otherwise.
ALPHABET is a string of characters (e.g., `ab` means the set {a, b}).

### `rex universal EXPR ALPHABET`

Print `true` if L(EXPR) contains every string over the given alphabet, `false` otherwise.

### `rex equivalent EXPR1 EXPR2 ALPHABET`

Print `true` if L(EXPR1) = L(EXPR2) over the given alphabet, `false` otherwise.

### `rex dot EXPR ALPHABET`

Print a Graphviz DOT digraph to stdout representing the finite state graph of EXPR over ALPHABET.

Requirements for the DOT output:
- Output must be a valid Graphviz `digraph`
- Each state is a node with a string label
- The start state has an incoming edge from an invisible node (shape=none, label="")
- Accepting states (those whose language contains the empty string) use `doublecircle` shape
- Non-accepting states use `circle` shape
- Each transition is a directed edge labeled with the alphabet character

### `rex compile EXPR ALPHABET OUTPUT_BINARY`

Construct the DFA for EXPR over ALPHABET, generate C source code implementing the DFA as a state machine, compile it with `gcc` into a standalone executable at OUTPUT_BINARY.

The compiled binary must:
- Read lines from stdin (one string per line)
- For each line, print `accept` if the string is in L(EXPR), `reject` otherwise
- Handle empty lines (empty string match) correctly
- Exit with code 0

### `rex flex-spec EXPR ALPHABET OUTPUT_L_FILE`

Construct the DFA for EXPR over ALPHABET, generate a valid `flex` lexical specification (`.l` file) at OUTPUT_L_FILE.

The generated `.l` file must:
- Be compilable with `flex -o lex.yy.c OUTPUT_L_FILE && gcc -o matcher lex.yy.c`
- The resulting binary reads stdin (without trailing newline) as a single input string
- Prints `accept` if the input is in L(EXPR), `reject` otherwise
- Use exclusive start conditions (`%x`) to represent DFA states
- Use `%option noyywrap`

## Language Semantics

- L(#) = {} (empty set)
- L(@) = {""} (set containing only the empty string)
- L(c) = {"c"} for character literal c
- L(r1 | r2) = L(r1) union L(r2)
- L(r1 r2) = { xy : x in L(r1), y in L(r2) }
- L(r*) = {""}  union  L(r)  union  L(rr)  union  L(rrr) union ...
- L(~r) = Sigma* \ L(r) (complement with respect to all strings over the alphabet)
- L(r1 & r2) = L(r1) intersect L(r2)
