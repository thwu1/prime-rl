# ORDER BY Bug Taxonomy

PostgreSQL maintains dual identifier resolution paths inherited from the SQL standard:

- **SQL-92 path** (bare identifier): resolves against SELECT-list aliases first
- **SQL-99 path** (any expression): resolves against FROM scope (table columns)

Various SQL constructs interact with these paths in surprising ways. Classify each bug into exactly one of these categories:

## alias_resolution

The ORDER BY bare identifier resolves to a SELECT-list alias when the table column was intended (or vice versa). This happens when an alias shadows a column name from the source table.

## identifier_mismatch

Quoted and unquoted identifiers follow different case-sensitivity rules. An unquoted identifier is normalized to lowercase before matching, so it may fail to match a mixed-case quoted alias, causing silent fallthrough to the FROM-scope column.

## scope_restriction

Certain SQL clauses have stricter or different resolution rules than standard ORDER BY. Window function ORDER BY, UNION ORDER BY, and GROUP BY each resolve identifiers in their own scope, which may not include SELECT-list aliases or may reject expressions entirely.

## expression_promotion

A syntactic modifier — type cast (::), COLLATE, or unary operator (+) — transforms a bare identifier into an expression, forcing PostgreSQL from the SQL-92 alias path to the SQL-99 FROM-scope path. An alias that worked as a bare name becomes invisible.

## ordering_constraint

Structural SQL requirements impose constraints on ORDER BY that go beyond identifier resolution. For example, DISTINCT ON requires ORDER BY to begin with the DISTINCT ON expressions.
