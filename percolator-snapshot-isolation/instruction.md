`/app/percolator/` contains a Python package implementing distributed transactions over a SQLite-backed multi-version key-value store. The skeleton code in `/app/percolator/storage.py` and `/app/percolator/client.py` has all core methods stubbed with `NotImplementedError`.

The storage layer (`KvTable`) manages three column families—`kv_write`, `kv_data`, and `kv_lock`—each keyed by `(key, ts)`. You must implement `read`, `write_record`, and `erase` as SQL operations against the pre-defined schema.

`MemoryStorage` implements the transaction protocol on top of `KvTable`:

- **`get(key, start_ts)`**: Read a key as of a snapshot timestamp. Must detect locks left by crashed transactions, determine whether the lock's primary committed or aborted, and clean up accordingly—either rolling forward (committing the secondary) or rolling back (erasing lock and data).
- **`prewrite(key, value, start_ts, primary_key)`**: Write-intent phase. Must check for write-write conflicts (any committed write after `start_ts`) and existing locks from other transactions.
- **`commit(key, start_ts, commit_ts, is_primary)`**: Finalize a prewrite by writing a commit record and erasing the lock. Must respect `CommitHooks` for simulating network failures (`drop_req`, `drop_resp`, `fail_primary`).
- **`back_off_maybe_clean_up_lock(key, caller_start_ts)`**: Lock resolution for secondary keys. Determine the primary's fate by querying `kv_write` for a commit record matching the lock's `start_ts`, then either roll forward or roll back the secondary.

`Client` orchestrates two-phase commit: buffer writes, prewrite all keys (designating one as primary), obtain a commit timestamp, commit primary first, then secondaries. Handle `RequestDroppedError` (definite failure) and `ResponseDroppedError` (ambiguous—primary may have committed) correctly.

The `/app/` directory is a git repository. Its history contains reference material relevant to the protocol design.

All tests in `/tests/test_state.py` must pass.