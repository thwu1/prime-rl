# ARIES Recovery — WAL Schema & Output Specification

## WAL Database (`/app/wal.db`)

All recovery state is stored in a SQLite database. Use `sqlite3 /app/wal.db` to explore the schema interactively.

### Tables

**`log_records`** — Write-Ahead Log entries

| Column | Type | Description |
|---|---|---|
| `lsn` | INTEGER PK | Log Sequence Number (monotonically increasing) |
| `record_type` | TEXT | `BEGIN`, `UPDATE`, `COMMIT`, `ABORT`, `END`, `CHECKPOINT_BEGIN`, `CHECKPOINT_END`, `CLR`, `NTA_COMPLETE` |
| `txn_id` | INTEGER | Transaction identifier (NULL for checkpoint records) |
| `page_id` | INTEGER | Page modified (NULL for non-page-modifying records) |
| `table_name` | TEXT | Table the page belongs to |
| `before_value` | INTEGER | Page value before this operation |
| `after_value` | INTEGER | Page value after this operation |
| `prev_lsn` | INTEGER | Previous LSN in this transaction's chain |
| `undo_next_lsn` | INTEGER | For CLR/NTA_COMPLETE: LSN to continue undo from |
| `description` | TEXT | Human-readable description of the operation |

**`checkpoint_data`** — Dirty page table and transaction table snapshots from the most recent checkpoint

| Column | Type | Description |
|---|---|---|
| `checkpoint_lsn` | INTEGER | LSN of the CHECKPOINT_END record |
| `data_type` | TEXT | `DPT` (dirty page table) or `TXN_TABLE` (transaction table) |
| `entry_key` | INTEGER | Page ID (for DPT) or Transaction ID (for TXN_TABLE) |
| `rec_lsn` | INTEGER | Recovery LSN — first log record that dirtied this page (DPT only) |
| `status` | TEXT | Transaction status at checkpoint time (TXN_TABLE only) |
| `last_lsn` | INTEGER | Most recent LSN for this transaction (TXN_TABLE only) |

**`page_baseline`** — Initial page values before any transaction

| Column | Type | Description |
|---|---|---|
| `page_id` | INTEGER PK | Page identifier |
| `table_name` | TEXT | Owning table |
| `initial_value` | INTEGER | Page value before any transaction modified it |

**`master_record`** — Points to the most recent successful checkpoint

| Column | Type | Description |
|---|---|---|
| `checkpoint_lsn` | INTEGER | LSN of the CHECKPOINT_BEGIN for the most recent checkpoint |

### Views

- **`transaction_summary`** — Per-transaction aggregation of log activity
- **`page_operations`** — Per-page listing of all operations
- **`nta_records`** — All NTA_COMPLETE records with their chain pointers

## Crash Diagnostic Report (`/app/crash_report.json`)

The crash report is a deeply nested JSON document capturing full system state at the moment of the second crash. The data critical for recovery is the set of pages that were successfully flushed to disk, located at:

```
.crash_report.system_state_at_crash.disk_manager.flushed_pages
```

Each entry contains `page_id` and `on_disk_page_lsn`. Pages **not** listed in this array were never flushed to disk; their on-disk pageLSN should be treated as `-1` for redo decisions.

## Record Type Semantics

**UPDATE** — Modifies a page. Has `before_value` (pre-image) and `after_value` (post-image). Undoable during the undo phase.

**CLR** (Compensation Log Record) — Written during undo to compensate for a previous UPDATE. During redo, apply `after_value` just like an UPDATE. During undo, a CLR is **not undone**; instead, follow `undo_next_lsn` to continue the undo chain.

**NTA_COMPLETE** (Nested Top Action completion) — A dummy CLR that marks the end of a nested top action. NTAs protect structural modifications (e.g., B+ tree index splits) that must persist regardless of the enclosing transaction's outcome. During undo, follow `undo_next_lsn` to skip over the protected operations. The page modifications between `undo_next_lsn` and this record's LSN (for the same transaction) are permanently committed and must **never** be undone, even if the parent transaction aborts.

## Redo Decision Criteria

A log record with type UPDATE or CLR is redone if and only if **all** of the following hold:

1. The record's page is present in the Dirty Page Table (DPT)
2. The record's LSN ≥ the page's `recLSN` in the DPT
3. The record's LSN > the page's on-disk `pageLSN` (from the crash report; `-1` for unflushed pages)

## Analysis Phase — Checkpoint Processing

When processing `CHECKPOINT_END`, merge the checkpoint's DPT and transaction table snapshots:

- **DPT**: Checkpoint entries **replace** any existing in-memory entries for the same page (the checkpoint is authoritative).
- **TXN_TABLE**: For each checkpoint entry, if the transaction has not already ended, add it (or update `last_lsn` if the checkpoint's value is ≥ the current value). Advance status only forward (RUNNING → ABORTING/COMMITTING, never backward).

After analysis, set any remaining RUNNING transactions to RECOVERY_ABORTING.

## Output Format (`/app/recovery_output.json`)

```json
{
  "analysis_dpt": {"<page_id>": <recLSN>, ...},
  "analysis_txn_table": {"<txn_id>": {"status": "<STATUS>", "last_lsn": <lsn>}, ...},
  "redo_lsns": [<lsn>, ...],
  "undo_lsns": [<lsn>, ...],
  "final_page_states": {"<page_id>": <value>, ...},
  "committed_txns": [<txn_id>, ...],
  "aborted_txns": [<txn_id>, ...],
  "nta_protected_pages": [<page_id>, ...]
}
```

**Field definitions:**

- `analysis_dpt` — DPT after analysis completes (string page ID keys → integer recLSN values)
- `analysis_txn_table` — Active transactions after analysis (only those not yet ended; string txn ID keys)
- `redo_lsns` — Ordered list of LSNs of records that were redone during the redo phase
- `undo_lsns` — Ordered list of LSNs of UPDATE records that were undone (do not include CLR/NTA_COMPLETE chain traversals)
- `final_page_states` — Value of every page in `page_baseline` after all three recovery phases complete (string page ID keys)
- `committed_txns` — Sorted transaction IDs that committed
- `aborted_txns` — Sorted transaction IDs that were aborted (rolled back)
- `nta_protected_pages` — Sorted page IDs whose modifications persisted due to NTA protection despite their parent transaction aborting
