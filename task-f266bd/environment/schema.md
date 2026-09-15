# WAL Database Schema & Output Format

## WAL Database (`/app/wal.db`)

Use `sqlite3 /app/wal.db` to explore interactively.

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
| `undo_next_lsn` | INTEGER | For CLR/NTA_COMPLETE: chain pointer |
| `description` | TEXT | Human-readable description of the operation |

**`checkpoint_data`** — Dirty page table and transaction table snapshots from the most recent checkpoint

| Column | Type | Description |
|---|---|---|
| `checkpoint_lsn` | INTEGER | LSN of the CHECKPOINT_END record |
| `data_type` | TEXT | `DPT` (dirty page table) or `TXN_TABLE` (transaction table) |
| `entry_key` | INTEGER | Page ID (for DPT) or Transaction ID (for TXN_TABLE) |
| `rec_lsn` | INTEGER | First log record that dirtied this page (DPT only) |
| `status` | TEXT | Transaction status at checkpoint time (TXN_TABLE only) |
| `last_lsn` | INTEGER | Most recent LSN for this transaction (TXN_TABLE only) |

**`master_record`** — Points to the most recent successful checkpoint

| Column | Type | Description |
|---|---|---|
| `checkpoint_lsn` | INTEGER | LSN of the CHECKPOINT_BEGIN for the most recent checkpoint |

### Views

- **`transaction_summary`** — Per-transaction aggregation of log activity
- **`page_operations`** — Per-page listing of all operations
- **`nta_records`** — NTA_COMPLETE records with their chain pointers

## Record Types

- **BEGIN** — Transaction start marker.
- **UPDATE** — Page modification. `before_value`/`after_value` capture the state change. `prev_lsn` links to the previous record of the same transaction.
- **COMMIT** — Transaction declared committed.
- **ABORT** — Transaction declared aborted.
- **END** — Transaction lifecycle fully complete (all post-outcome work done).
- **CHECKPOINT_BEGIN** / **CHECKPOINT_END** — Fuzzy checkpoint boundaries. Associated DPT and transaction table snapshots are stored in the `checkpoint_data` table.
- **CLR** (Compensation Log Record) — Records the compensation of a prior update. `after_value` is the compensating value applied to the page. `undo_next_lsn` points to the next record in the transaction's backward chain, past the compensated operation.
- **NTA_COMPLETE** (Nested Top Action) — Marks the completion of a nested top action protecting structural index modifications. `undo_next_lsn` points past the protected operation range. Modifications between `undo_next_lsn` and this record's LSN (same transaction) are structurally committed and must persist regardless of the enclosing transaction's outcome.

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

- `analysis_dpt` — Dirty page table after the analysis pass completes (string page ID keys, integer recLSN values)
- `analysis_txn_table` — Active transactions after analysis (only those not yet ended; string txn ID keys). Status values: `RUNNING`, `COMMITTING`, `RECOVERY_ABORTING`, `COMPLETE`.
- `redo_lsns` — Ordered list of LSNs of records that were re-applied
- `undo_lsns` — Ordered list of LSNs of UPDATE records that were reversed (do not include CLR/NTA_COMPLETE chain traversals)
- `final_page_states` — Value of every database page after full recovery completes (string page ID keys)
- `committed_txns` — Sorted transaction IDs that committed
- `aborted_txns` — Sorted transaction IDs that were aborted (rolled back)
- `nta_protected_pages` — Sorted page IDs whose modifications persisted due to NTA protection despite their parent transaction aborting
