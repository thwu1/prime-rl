Implement a TQL (Text Query Language) interpreter as an executable at `/app/tql`.

TQL is a SQL-like query language for querying Tab-Separated Values files. The complete language specification is at `/spec.md`. Sample data files are in `/data/`.

The tool accepts a single query string as a command-line argument and outputs tab-separated results to stdout with a header row. NULL values are rendered as the literal string `NULL`. Errors are reported to stderr with a non-zero exit code.

The implementation must handle all features described in the specification: JOINs (INNER, LEFT, self), GROUP BY with HAVING, aggregate functions (COUNT, SUM, AVG, MIN, MAX, MEDIAN), subqueries (scalar, IN, EXISTS including correlated), CASE expressions, SQL three-valued NULL logic, LIKE pattern matching, BETWEEN, COALESCE, string/math functions, DISTINCT, and ORDER BY with NULLS FIRST/LAST.