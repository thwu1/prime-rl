# Column-Store Join Query Engine — Format Reference

## Binary Relation Format

Each relation is stored as a binary file with little-endian byte order in column-major layout:

| Offset | Size | Content |
|--------|------|---------|
| 0 | 8 bytes | `uint64` — number of rows (N) |
| 8 | 8 bytes | `uint64` — number of columns (M) |
| 16 | 8×N bytes | Column 0: N `uint64` values |
| 16+8N | 8×N bytes | Column 1: N `uint64` values |
| ... | ... | ... |

Data is column-major: all values of column 0 appear first (row 0 through N-1), then all values of column 1, and so on. All values are unsigned 64-bit integers in little-endian format.

## Relations

Six relation files in `/app/data/`:

| File | Rows | Columns |
|------|------|---------|
| `r0.bin` | 200 | 4 |
| `r1.bin` | 300 | 3 |
| `r2.bin` | 150 | 4 |
| `r3.bin` | 400 | 3 |
| `r4.bin` | 250 | 4 |
| `r5.bin` | 180 | 3 |

CSV exports and a SQLite catalog (`/app/catalog.db` with tables `r0`–`r5`) are also available.

## Query Format

Queries in `/app/workload.txt`, one per line:

```
<relation_ids>|<predicates>|<projections>
```

### Relation IDs

Space-separated global relation file indices (e.g., `0 2 4` uses `r0.bin`, `r2.bin`, `r4.bin`). These are bound to query-local **positions**: the first listed relation is position 0, the second is position 1, etc. All column references in predicates and projections use these positions.

### Predicates

`&`-separated. Two types, distinguished by whether the right-hand side contains a `.`:

- **Join predicate** `X.Y=A.B` — equi-join between position X column Y and position A column B
- **Filter predicate** `X.Y{=|<|>}C` — compare position X column Y against integer constant C

### Projections

Space-separated column references `X.Y` (position.column). For each, compute `SUM` over all qualifying tuples.

## Output Format

One line per query in `/app/output.txt`:
- Space-separated SUM values, one per projection
- `NULL` for each projection if no tuples qualify

## Example

Query: `0 2 4|0.1=1.2&1.0=2.1&0.1>3000|0.0 1.1`

- Bind: position 0 → r0, position 1 → r2, position 2 → r4
- `0.1=1.2`: join pos0.col1 = pos1.col2
- `1.0=2.1`: join pos1.col0 = pos2.col1
- `0.1>3000`: filter pos0.col1 > 3000
- Project: SUM(pos0.col0), SUM(pos1.col1)

SQL equivalent:
```sql
SELECT SUM("0".c0), SUM("1".c1)
FROM r0 "0", r2 "1", r4 "2"
WHERE "0".c1 = "1".c2
  AND "1".c0 = "2".c1
  AND "0".c1 > 3000
```
