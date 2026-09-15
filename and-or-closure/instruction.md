A SQLite database at `/app/lattice.db` contains integer sets stored as packed binary BLOBs. Each test case row holds `n` (the set size) and `values_packed` (a BLOB of `n` unsigned 64-bit little-endian integers).

For each test case, compute the **AND-OR closure size** — the cardinality of the smallest superset B ⊇ A closed under bitwise AND and bitwise OR — and write the answer into the `results` table (`test_id`, `closure_size`).

Implement the solver in C++ within the CMake project at `/app/project/`. A skeleton `CMakeLists.txt` is provided; add your source files under `/app/project/src/` and configure the build. Use CMake to configure and compile in `/app/project/build/`.

Create `/app/pipeline.sh` to orchestrate the full pipeline: CMake build, data extraction from SQLite via `sqlite3`, solver execution, and result insertion back into the database.

Inspect the database schema with `sqlite3 /app/lattice.db '.schema'`. The binary blob format and table definitions are documented in `/app/SCHEMA.md`. The mathematical problem description is in `/app/problem.txt`.

Test cases range from trivial (n=1) to large (n=200,000+) with values up to 2^40. Your solution must handle all cases within reasonable time and memory limits.