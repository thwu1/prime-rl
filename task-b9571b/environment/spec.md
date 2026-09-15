# SQLLogicTest Runner Specification

## Overview

The sqllogictest format is a domain-specific test format used by database systems (DuckDB, SQLite, CockroachDB, DataFusion) to define SQL conformance and regression tests. Each `.test` file contains a sequence of SQL statements paired with expected results that can be automatically verified.

Your task is to implement a Python runner that parses these `.test` files, executes the SQL against DuckDB, and verifies the results.

## File Format

A `.test` file consists of a sequence of **blocks** separated by blank lines. Lines starting with `#` are comments and must be ignored. Blank lines between blocks are ignored.

Each block begins with a **directive** on its first line. SQL statements within a block can span multiple lines and end at either a `----` separator or the next blank line.

---

## Directives

### `statement ok`

```
statement ok [@connection_name]
<sql>
```

Executes the SQL statement and expects it to succeed without error. The SQL can span multiple lines. The block ends at the next blank line.

If `@connection_name` is specified, the statement is executed on the named connection instead of the default connection (see **Multi-Connection Execution**).

### `statement error`

```
statement error [@connection_name]
<sql>
----
<expected_error_substring>
```

Executes the SQL and expects it to **fail**. If a `----` separator and error message text follow the SQL, the actual error message must **contain** the specified text as a substring (case-sensitive). If no `----` section is present, any error is acceptable.

If `@connection_name` is specified, the statement is executed on the named connection.

### `query`

```
query <type_string> [sort_mode] [label] [@connection_name]
<sql>
----
<expected_results>
```

Executes a SQL query and verifies the results.

**Parameters:**
- **type_string** (required): A string of characters where each character represents one result column.
  - `I` - Integer
  - `T` - Text/VARCHAR
  - `R` - Real/Float
  - The **length** of this string determines the expected number of columns (e.g., `II` = 2 columns, `ITR` = 3 columns).

- **sort_mode** (optional, default `nosort`):
  - `nosort` - Compare results in the order returned by the database.
  - `rowsort` - Both actual and expected rows are sorted lexicographically (as tab-joined row strings) before comparison.
  - `valuesort` - All individual values (from both actual and expected) are flattened into a single list, sorted lexicographically, and compared one-per-line.

- **label** (optional): A string label for equivalence checking. All queries sharing the same label must produce identical results, verified by comparing MD5 hashes of their result values. When using a label, the expected results after `----` may be omitted (but `----` must still be present).

- **@connection_name** (optional): Execute on the named connection. Any token starting with `@` on the directive line is treated as a connection name.

**Expected Results Format (after `----`):**

1. **Row format** (for `nosort` and `rowsort`): Each line is one row. Column values within a row are separated by **tab characters** (`\t`).

2. **Value format** (for `valuesort`): Each line contains exactly one value. All values are listed in sorted order.

3. **Hash format**: A single line matching: `<N> values hashing to <md5hex>` where `N` is the total number of scalar values (rows x columns) and `<md5hex>` is the expected MD5 hex digest. See **Hash Computation** below.

4. **Empty**: If the `----` is present but nothing follows (or only blank lines follow), verification is label-only.

### `loop`

```
loop <variable> <start> <end>
<body>
endloop
```

Repeats `<body>` for each integer value from `start` (**inclusive**) to `end` (**exclusive**), like Python's `range(start, end)`. Within the body, occurrences of `${variable}` are replaced with the current iteration value. The body can contain any directives (including nested loops).

### `foreach`

```
foreach <variable> <value1> <value2> <value3> ...
<body>
endforeach
```

Repeats `<body>` for each value in the space-separated value list. Within the body, occurrences of `${variable}` are replaced with the current value.

### `require`

```
require <extension_name>
```

Checks if the named DuckDB extension is available. If the extension cannot be loaded, the **entire** test file is **skipped** (treated as success, not failure). Place `require` directives at the top of the file before any SQL execution.

### `hash_threshold`

```
hash_threshold <N>
```

Sets a threshold: any query result with more than `N` total scalar values automatically uses hash verification instead of line-by-line comparison. When auto-hashing is triggered and the expected result is provided as individual value lines, the runner hashes both the actual result values and the expected values and compares the two hashes.

### `reconnect`

```
reconnect
```

Drops all connections (default and named) and creates fresh connections to the same underlying database. Persistent state (tables, data, schemas) survives reconnection, but connection-local state (named cursor references) is reset. After reconnect, new named connections can be created as needed.

---

## Multi-Connection Execution

Database test scenarios often require verifying behavior across multiple concurrent connections. The runner supports named connections specified by an `@`-prefixed identifier on any `statement` or `query` directive line.

**Connection model:**
- The runner maintains a **database** (a single DuckDB instance) and a set of **connections** (cursors created from that database).
- The **default connection** is used when no `@name` is specified.
- **Named connections** are created lazily: the first reference to `@con1` creates a new cursor from the database.
- All connections share the same database, so persistent objects (tables, views, data) are visible across connections.
- Named connections maintain independent cursor state.

**Example:**
```
statement ok
CREATE TABLE shared(x INTEGER)

statement ok @writer
INSERT INTO shared VALUES (42)

query I @reader
SELECT x FROM shared
----
42
```

---

## Value Representation

When converting database result values to their string representation for comparison:

| Database value | String representation |
|---|---|
| SQL NULL | `NULL` |
| Empty string `''` | `(empty)` |
| Boolean TRUE | `true` |
| Boolean FALSE | `false` |
| Integers | Standard decimal string (e.g., `42`, `-7`) |
| Other types | `str(value)` - Python's default string conversion |

---

## Regex Matching

Individual expected values can use regex patterns instead of exact strings:

- `<REGEX>:pattern` - The actual value must **match** the regex pattern.
- `<!REGEX>:pattern` - The actual value must **not match** the regex pattern.

Matching uses `re.DOTALL` mode (`.` matches any character including newlines), which is necessary for verifying multi-line values such as EXPLAIN query plan output.

When the expected row is tab-separated, regex matching applies per-value: split both actual and expected rows by tab, then compare each pair individually.

**Example - EXPLAIN plan verification:**
```
statement ok
PRAGMA explain_output = PHYSICAL_ONLY;

query TT
EXPLAIN SELECT * FROM my_table
----
physical_plan	<REGEX>:.*SEQ_SCAN.*
```

The EXPLAIN query returns two columns. The first column (`physical_plan`) is compared exactly; the second column (the plan text, which may contain newlines) is matched against the regex with DOTALL semantics.

---

## Hash Computation

To compute the hash of a query result:

1. Collect all result values in **row-major order** (left to right within each row, top to bottom across rows).
2. Convert each value to its string representation (see Value Representation above).
3. Join all values with newline characters, with a **trailing newline**: `"val1\nval2\n...\nvalN\n"`
4. Compute the **MD5** hex digest of the UTF-8 encoded string.

Example: a 3-row, 2-column result `[(1, 'a'), (2, 'b'), (3, 'c')]` produces:
- Values: `["1", "a", "2", "b", "3", "c"]`
- Hash input: `"1\na\n2\nb\n3\nc\n"`
- Hash: `md5("1\na\n2\nb\n3\nc\n".encode()).hexdigest()`

---

## Runner CLI Interface

Your runner must be invocable as:

```
python3 /app/sqllogictest_runner.py <test_file_path>
```

**Exit codes:**
- `0` - All tests in the file passed, OR the test was skipped due to an unmet `require` directive.
- Non-zero - One or more tests failed, or an error occurred (e.g., file not found).

The runner should output diagnostic information to stdout/stderr to aid debugging.
