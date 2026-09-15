# Crash Recovery Tool — Reference

## Input Sources

Recovery state is spread across three data sources. All must be read and correlated to perform correct recovery analysis.

### 1. SQLite Crash Database (`crash.db`)

Follows the schema in `/app/schema.sql`. Use `sqlite3 <db> .schema` to inspect interactively.

#### wal_records
Ordered log of all database operations before the crash.
- `lsn` (INTEGER PRIMARY KEY) — Log Sequence Number, monotonically increasing
- `record_type` (TEXT) — One of: UPDATE, CLR, COMMIT, ABORT, END, BEGIN_CHECKPOINT, END_CHECKPOINT
- `txn_id` (INTEGER) — Transaction identifier (NULL for checkpoint records)
- `prev_lsn` (INTEGER) — Previous log record LSN for the same transaction (NULL if first record for that transaction)
- `page_id` (INTEGER) — Affected data page (UPDATE and CLR records only)
- `undo_next_lsn` (INTEGER) — Next LSN in the undo chain (CLR records only); points to where undo should continue if this CLR's transaction needs further reversal

#### crash_state
Recovery metadata as key-value pairs.
- Key `master_record_lsn`: LSN of the most recent `BEGIN_CHECKPOINT` record. Forward log analysis begins from this point.

#### checkpoint_txn_snapshot
Transaction state captured during a checkpoint, keyed by the associated `END_CHECKPOINT` record's LSN.
- `checkpoint_lsn` — The LSN of the `END_CHECKPOINT` record this snapshot belongs to
- `txn_id`, `status`, `last_lsn` — Transaction state at checkpoint time

Note: checkpoints are *fuzzy* — the snapshot reflects the state at `BEGIN_CHECKPOINT` time, so it may be stale relative to log records written between `BEGIN_CHECKPOINT` and `END_CHECKPOINT`.

#### checkpoint_dpt_snapshot
Dirty page state captured during a checkpoint.
- `checkpoint_lsn` — The `END_CHECKPOINT` record's LSN
- `page_id`, `rec_lsn` — Pages that were dirty at checkpoint time, with the LSN of their earliest unflushed modification

### 2. Binary Page State (`<crash.db>.pgstate`)

Flushed page metadata in the PGST binary format (see `/app/BINARY_FORMAT.md`). Indicates which data pages were successfully written to stable storage before the crash. Pages absent from this file were never flushed; treat their on-disk state as nonexistent (effective LSN of −1).

### 3. Binary WAL Suffix (`<crash.db>.walsuffix`)

Additional WAL records in the WAL1 binary format (see `/app/BINARY_FORMAT.md`). Contains log records that were appended to the write-ahead log after the SQLite WAL export. These must be merged with the SQLite WAL records (ordered by LSN) before analysis. This file may not exist if all records are already in the SQLite database.

## Log Record Types

| Type | Page-modifying | Reversible | Notes |
|------|:-:|:-:|-------|
| UPDATE | Yes | Yes | Normal data page modification |
| CLR | Yes | No | Compensation for a previously reversed update; has `undo_next_lsn` |
| COMMIT | No | No | Transaction declared durable |
| ABORT | No | No | Transaction marked for reversal |
| END | No | No | Transaction fully completed |
| BEGIN_CHECKPOINT | No | No | Checkpoint interval start |
| END_CHECKPOINT | No | No | Checkpoint interval end; snapshot data in checkpoint tables |

## Transaction Status Progression

- RUNNING → COMMITTING (on COMMIT record) → removed (on END record)
- RUNNING → ABORTING (on ABORT record) → removed (on END record)
- COMMITTING and ABORTING are both considered more advanced than RUNNING

## Output JSON

```json
{
  "analysis": {
    "transaction_table": {
      "<txn_id>": {"status": "<STATUS>", "last_lsn": <int>}
    },
    "dirty_page_table": {
      "<page_id>": <rec_lsn>
    }
  },
  "redo": [<LSN, ...>],
  "undo": {
    "clrs": [
      {"undone_lsn": <int>, "txn_id": <int>, "page_id": <int>, "undo_next_lsn": <int|null>}
    ],
    "ended_txns": [<txn_id, ...>]
  }
}
```

### analysis.transaction_table
Transactions that remain active after a complete forward scan of the log from the checkpoint, with checkpoint snapshot data incorporated. Transactions that received `END` records during the scan are excluded. Keys are string transaction IDs.

### analysis.dirty_page_table
Pages with potentially unflushed modifications after forward scan and checkpoint data incorporation. Maps string page ID to `rec_lsn`.

### redo
LSNs of page-modifying records that must be replayed, in ascending order. A record's effects need replay only when the on-disk page state does not already reflect them.

### undo.clrs
Compensation records produced during transaction reversal, in generation order. Reversing an UPDATE produces a CLR recording the undone LSN, transaction, page, and the next undo target (the `prev_lsn` of the undone record). CLR records already present in the log are not themselves reversed — their `undo_next_lsn` is followed instead.

### undo.ended_txns
Transactions whose reversal completed (undo chain exhausted), in completion order. When multiple transactions are being reversed, records are processed in descending LSN order across all active undo chains.
