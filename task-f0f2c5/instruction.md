Implement a Python interpreter for a subset of the DaeDaLus parser specification language. DaeDaLus is a DSL for formally specifying binary data formats. Your interpreter must parse `.ddl` specification files and use them to parse binary input files, producing structured JSON output.

**Architecture constraint:** The DDL spec tokenizer must be implemented as a flex lexer specification (`.l` file) compiled into a shared library (`.so`) via gcc, and loaded from Python through ctypes. The environment provides `flex` and `gcc`. A pure Python tokenizer will not pass verification.

Your solution must produce:
- `/app/ddl_lexer.l` — Flex lexer specification for DDL source tokens (keywords, identifiers, literals, operators, comments with nesting)
- `/app/build.sh` — Shell script that runs flex on the `.l` file and compiles the output with gcc into `/app/libddl_lexer.so`
- `/app/ddl_interpreter.py` — Main entry point: `python3 /app/ddl_interpreter.py <spec.ddl> <input.bin>`. Must load `libddl_lexer.so` via ctypes for tokenization. On success: print JSON to stdout, exit 0. On failure: print error to stderr, exit 1.

Three DDL specifications are provided in `/app/specs/`: `simple_msg.ddl` (message container with bitdata enum tags), `sensor_data.ddl` (sensor archive with tagged union readings via `First`), and `packet.ddl` (parameterized packet parser with `case` dispatch and `$$` explicit results).

## Required Language Subset

**Declarations:** `def Name = Body`, `def Name (param : type) = Body`, `bitdata Name where` (enum form `name = 0x01 : uint 8` and struct form `Name = { field : uint N, ... }`)

**Parsers:** `UInt8`, `BEUInt16`, `BEUInt32`, `Match [byte, ...]`, `Many P` (zero-or-more), `Many count P` (exactly N), `END`, `Fail "msg"`

**Block syntax (layout-sensitive):** `block` with named fields (`name = P`), local `let` bindings, explicit result (`$$ = P`), unnamed statements

**Alternatives:** `First` with named alternatives (layout-sensitive, backtracking), `P <| Q`, tagged union literals `{| tag = expr |}`

**Control:** `case expr of` with integer/wildcard patterns, `Guard (expr)`

**Character classes:** `$[byte]`, `$[low .. high]`

**Expressions:** integer/hex literals, `as uint N`, `as? BitdataType`, `expr.field`, comparisons (`<=`, `>=`, `==`), arithmetic (`+`, `-`, `*`)

**Other:** `--` line comments, `{- -}` block comments (nestable), entry point is `def Main`

## JSON Encoding

- Integers -> JSON numbers
- Byte arrays from `Many` -> JSON arrays of numbers
- Named block fields -> JSON object
- `$$` explicit result -> value directly (not wrapped)
- Tagged unions (`First` alternatives, `{| tag = val |}`) -> object with single key
- Bitdata enum coercion (`as?`) -> variant name as JSON string
- Bitdata struct coercion (`as?`) -> object with field names/values, MSB-first layout
- `Match`, `Guard`, unnamed statements -> not in output
- `let` bindings -> not in output