A SQLite database at `/app/forensic.db` was running in WAL mode when its host application crashed. The WAL file at `/app/forensic.db-wal` contains multiple committed transactions that were never checkpointed into the main database file. The main database reflects only the pre-transaction state.

Build a Python module at `/app/wal_forensics.py` that performs binary-level forensic analysis of the WAL file: parsing its internal structures, validating data integrity across the full chain of entries, identifying transaction boundaries, and reconstructing standalone database snapshots at arbitrary transaction points.

The test suite at `/tests/test_state.py` specifies the exact interface your module must expose and the outcomes it must produce. Study it to determine required function signatures, return structures, and behavioral expectations (including corruption detection).

The environment includes `sqlite3`, binary inspection utilities (`xxd`, `hexdump`, `od`), and Python 3. The SQLite file format documentation is publicly available online.