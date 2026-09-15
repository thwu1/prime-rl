# TQL Specification v1.0

## Overview

TQL (Text Query Language) is a SQL-like query language for querying Tab-Separated Values (TSV) files. It provides a subset of SQL functionality for ad-hoc analysis of structured text data.

## Invocation

```
tql <query>
```

The query is passed as a single command-line argument. Results are written to standard output in TSV format. Errors are written to standard error with a non-zero exit code.

## Data Sources

### File Resolution

Table names in queries correspond to TSV files in the data directory (`/data/`). A reference to table `employees` resolves to `/data/employees.tsv`. Table names are case-insensitive.

### TSV Format

- First row contains column headers
- Fields are separated by tab characters
- The literal string `NULL` (case-insensitive) represents a SQL NULL value
- An empty string is an empty string, not NULL

### Type Inference

Column types are inferred from non-NULL data values:

1. If all non-NULL values parse as integers → column type is **INTEGER**
2. Else if all non-NULL values parse as numbers (int or float) → column type is **REAL**
3. Otherwise → column type is **TEXT**

## Query Syntax

TQL supports a single SELECT statement with the following clauses (in order):

```
SELECT [DISTINCT] select_list
FROM table_ref [alias]
[join_clause ...]
[WHERE condition]
[GROUP BY expr_list]
[HAVING condition]
[ORDER BY order_list]
[LIMIT count [OFFSET skip]]
```

### SELECT Clause

- `*` expands to all columns from all tables
- `table.*` expands to all columns from a specific table
- Expressions can be aliased with `AS alias`
- `DISTINCT` removes duplicate rows from the result

### FROM Clause

- References a TSV file by name (without `.tsv` extension)
- Optional alias: `FROM employees e`

### JOIN Clause

- `INNER JOIN table ON condition` — only matching rows from both sides
- `LEFT JOIN table ON condition` — all rows from left table; NULLs for non-matching right rows
- Multiple joins are supported and evaluated left to right
- Self-joins (joining a table with itself using different aliases) are supported

### WHERE Clause

Standard boolean filtering. Only rows where the condition evaluates to TRUE are included. Rows where the condition is FALSE or UNKNOWN are excluded.

### GROUP BY Clause

Groups rows by one or more expressions. Non-aggregated columns in SELECT should appear in GROUP BY.

### HAVING Clause

Filters groups after aggregation. Same semantics as WHERE but operates on grouped/aggregated data.

### ORDER BY Clause

- `ASC` (default) or `DESC`
- `NULLS FIRST` or `NULLS LAST`
  - Default for ASC: NULLS FIRST (NULLs are considered smaller than all other values)
  - Default for DESC: NULLS LAST
- Multiple sort keys separated by commas

### LIMIT / OFFSET

- `LIMIT n` returns at most n rows
- `OFFSET m` skips the first m rows (used after LIMIT)

## Expressions

### Literals

- Integers: `42`, `-7`
- Floats: `3.14`, `-0.5`
- Strings: `'hello'`, `'it''s'` (single-quoted, `''` escapes a literal single quote)
- NULL: the keyword `NULL`

### Column References

- `column_name` — unqualified
- `table.column_name` or `alias.column_name` — qualified

### Arithmetic Operators

| Operator | Description |
|----------|-------------|
| `+` | Addition |
| `-` | Subtraction |
| `*` | Multiplication |
| `/` | Division (integer division for two integers, float otherwise) |
| `%` | Modulo |

All arithmetic with NULL yields NULL. Division by zero yields NULL.

### String Operator

| Operator | Description |
|----------|-------------|
| `\|\|` | String concatenation (NULL propagating) |

### Comparison Operators

| Operator | Description |
|----------|-------------|
| `=` | Equal |
| `!=`, `<>` | Not equal |
| `<` | Less than |
| `>` | Greater than |
| `<=` | Less than or equal |
| `>=` | Greater than or equal |

Any comparison with NULL yields UNKNOWN.

### Boolean Operators

| Operator | Description |
|----------|-------------|
| `AND` | Logical AND (three-valued) |
| `OR` | Logical OR (three-valued) |
| `NOT` | Logical NOT (three-valued) |

Three-valued logic truth tables:

- `TRUE AND UNKNOWN` → UNKNOWN
- `FALSE AND UNKNOWN` → FALSE
- `TRUE OR UNKNOWN` → TRUE
- `FALSE OR UNKNOWN` → UNKNOWN
- `NOT UNKNOWN` → UNKNOWN

### Predicates

- `expr IS NULL` — true if expr is NULL
- `expr IS NOT NULL` — true if expr is not NULL
- `expr IN (value_list)` — true if expr equals any value in the list
- `expr IN (subquery)` — true if expr equals any value returned by the subquery
- `expr NOT IN (value_list)` — true if expr does not equal any value; UNKNOWN if NULL is involved and no definite match is found
- `expr NOT IN (subquery)` — same semantics
- `expr BETWEEN low AND high` — equivalent to `expr >= low AND expr <= high` (inclusive)
- `expr NOT BETWEEN low AND high`
- `expr LIKE pattern` — pattern matching: `%` matches any sequence of zero or more characters, `_` matches exactly one character. **Case-sensitive.**
- `expr NOT LIKE pattern`
- `EXISTS (subquery)` — true if the subquery returns at least one row
- `NOT EXISTS (subquery)` — true if the subquery returns no rows

### CASE Expression

```sql
CASE
  WHEN condition1 THEN result1
  WHEN condition2 THEN result2
  ...
  ELSE default_result
END
```

Evaluates conditions in order, returns the result for the first TRUE condition. If no condition is TRUE, returns the ELSE result (or NULL if no ELSE).

### Subqueries

- **Scalar subquery**: a subquery that returns a single value, usable in comparisons (e.g., `WHERE salary > (SELECT AVG(salary) FROM employees)`)
- **IN subquery**: a subquery that returns a set of values for membership testing
- **EXISTS subquery**: tests whether the subquery produces any rows
- **Correlated subqueries**: subqueries that reference columns from the outer query are supported

## Functions

### Aggregate Functions

| Function | Description |
|----------|-------------|
| `COUNT(*)` | Count all rows including those with NULLs |
| `COUNT(expr)` | Count rows where expr is not NULL |
| `COUNT(DISTINCT expr)` | Count distinct non-NULL values of expr |
| `SUM(expr)` | Sum of non-NULL values |
| `AVG(expr)` | Average of non-NULL values (returns REAL) |
| `MIN(expr)` | Minimum non-NULL value |
| `MAX(expr)` | Maximum non-NULL value |
| `MEDIAN(expr)` | Median of non-NULL values. For odd count: the middle value. For even count: the average of the two middle values. |

All aggregate functions except `COUNT(*)` ignore NULL values. If all values are NULL, the result is NULL (except `COUNT` which returns 0).

### Scalar Functions

| Function | Description |
|----------|-------------|
| `UPPER(str)` | Convert string to uppercase |
| `LOWER(str)` | Convert string to lowercase |
| `LENGTH(str)` | Return the length of the string |
| `SUBSTR(str, start, len)` | Return substring starting at position `start` (1-indexed) with length `len` |
| `TRIM(str)` | Remove leading and trailing whitespace |
| `COALESCE(expr1, expr2, ...)` | Return the first non-NULL argument |
| `ABS(num)` | Absolute value |
| `ROUND(num, digits)` | Round to the specified number of decimal places |

All scalar functions return NULL if any required argument is NULL (except COALESCE which specifically handles NULLs).

## NULL Semantics

TQL follows standard SQL three-valued logic (TRUE, FALSE, UNKNOWN):

- Any arithmetic operation with NULL yields NULL
- Any comparison with NULL yields UNKNOWN (not TRUE or FALSE)
- `NULL = NULL` is UNKNOWN, **not** TRUE — use `IS NULL` instead
- WHERE and HAVING clauses only include rows where the condition is TRUE (not UNKNOWN)
- `IS NULL` / `IS NOT NULL` are the only way to definitively test for NULL
- Aggregate functions ignore NULL values (except `COUNT(*)`)
- `expr IN (... NULL ...)`: if no exact match among non-NULL values and NULL is present, result is UNKNOWN
- `expr NOT IN (...)`: if the expression value is NULL, or if NULL is in the list and no definite non-match, result is UNKNOWN

## Type Coercion

- In arithmetic contexts, TEXT values that represent valid numbers are converted to the appropriate numeric type
- In string concatenation (`||`), non-string values are converted to their text representation
- Comparisons between different types follow numeric affinity when possible

## Output Format

- Tab-separated values written to standard output
- First row contains column names (or aliases if specified)
- NULL values are output as the literal string `NULL`
- Integer values: no decimal point (e.g., `42`)
- Real values: natural decimal representation (e.g., `3.14`); integer-valued reals display without a decimal point (e.g., `200` not `200.0`)
