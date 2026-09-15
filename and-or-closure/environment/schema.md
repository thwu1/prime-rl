# Database Schema: lattice.db

## Tables

### test_cases

| Column        | Type    | Description                                          |
|---------------|---------|------------------------------------------------------|
| id            | INTEGER | Primary key, test case identifier (1-indexed)        |
| n             | INTEGER | Number of values in this test case                   |
| values_packed | BLOB    | Packed binary array of n unsigned 64-bit LE integers |

### results

| Column       | Type    | Description                                    |
|--------------|---------|------------------------------------------------|
| test_id      | INTEGER | Foreign key referencing test_cases.id           |
| closure_size | INTEGER | The AND-OR closure size for this test case      |

## Binary BLOB Format

The `values_packed` column stores the integer set as a contiguous array of
unsigned 64-bit integers in **little-endian** byte order. For a test case with
`n` values, the blob is exactly `n * 8` bytes.

To inspect a blob in sqlite3, use `hex(values_packed)`. Each value occupies
16 hex characters (8 bytes), least-significant byte first.

Example: the set {0, 1, 3, 5} is stored as 32 bytes:
```
00000000 00000000   (value 0)
01000000 00000000   (value 1)
03000000 00000000   (value 3)
05000000 00000000   (value 5)
```

To extract values programmatically, read the blob and unpack using
little-endian uint64 format (e.g., Python's `struct.unpack('<NQ', blob)`
where N is the count).
