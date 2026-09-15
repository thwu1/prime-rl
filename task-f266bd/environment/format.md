# ARIES Recovery: Log Format and Algorithm Reference

## Database Model

The database consists of numbered pages, each storing a single integer value.
All pages are initialized to value 0. Updates replace the entire page value.

## Log File Format (`log.jsonl`)

Each line is a JSON object representing one log record. All records have `lsn` (integer)
and `type` (string) fields. Record types and their additional fields:

### MASTER (always at LSN 0)
- `last_checkpoint_lsn`: LSN of the most recent successful BEGIN_CHECKPOINT record.
  This record is rewritten in place when a checkpoint completes successfully.

### BEGIN_CHECKPOINT
No additional fields. Marks the start of a fuzzy checkpoint.

### END_CHECKPOINT
- `dpt`: Dirty Page Table snapshot — `{page_id_str: recLSN, ...}`
- `txn_table`: Transaction Table snapshot — `{txn_id_str: [status_str, lastLSN], ...}`

The snapshot was taken at some point between the corresponding BEGIN_CHECKPOINT and this
record. Concurrent operations may have modified the actual tables since the snapshot was
taken, so the data may be stale.

### UPDATE
- `txn_id`: integer — transaction performing the write
- `prev_lsn`: integer — previous LSN for this transaction (0 if first operation)
- `page_id`: integer — page being modified
- `before`: integer — page value before the update
- `after`: integer — page value after the update

### CLR (Compensation Log Record)
Written during transaction rollback (abort/undo). Represents the undo of a previous update.
- `txn_id`: integer
- `prev_lsn`: integer
- `page_id`: integer — page being restored
- `after`: integer — the restored value (applied when this CLR is redone)
- `undo_next_lsn`: integer — LSN of the next record to undo for this transaction
  (follows the original record's prev_lsn chain, skipping already-compensated records)

### COMMIT
- `txn_id`: integer
- `prev_lsn`: integer

### ABORT
- `txn_id`: integer
- `prev_lsn`: integer

### END
- `txn_id`: integer
- `prev_lsn`: integer

## Flushed Pages (`flushed_pages.json`)

A JSON object mapping page ID (as string) to the pageLSN that was on disk at crash time.
Pages not listed have pageLSN 0 on disk (no updates were flushed).

The on-disk value of a flushed page equals the cumulative result of applying all UPDATE
and CLR records (in LSN order) whose LSN is <= that page's flushed pageLSN.

## ARIES Recovery Overview

ARIES recovery has three phases executed in sequence: **Analysis**, **Redo**, **Undo**.

### Analysis

Reconstructs the Dirty Page Table (DPT) and Transaction Table by scanning the log
forward from the last checkpoint. The DPT maps page IDs to their recovery LSN (recLSN),
which is the LSN of the earliest log record that may have dirtied the page since it was
last known to be clean. The transaction table tracks each active transaction's status
and lastLSN.

Key rules:
- Any record with a `txn_id` adds the transaction to the table (if absent) and updates
  its lastLSN to the record's LSN.
- UPDATE and CLR records add the page to the DPT if not already present (recLSN = LSN).
- COMMIT sets status to COMMITTING. ABORT sets status to RECOVERY_ABORTING.
- END removes the transaction from the table (mark as ended).
- END_CHECKPOINT processing: DPT entries from the checkpoint **replace** any existing
  entries. For the transaction table, skip transactions that have already ended; for
  others, add if absent, set lastLSN to the maximum of existing and checkpoint values,
  and advance the status only if the checkpoint status represents forward progress along
  a valid state transition path (RUNNING can advance to COMMITTING or RECOVERY_ABORTING;
  COMMITTING can advance to COMPLETE; RECOVERY_ABORTING can advance to COMPLETE; no
  backward transitions). Checkpoint status "ABORTING" should be treated as "RECOVERY_ABORTING".
- After the scan: transactions still COMMITTING are ended (removed). Transactions still
  RUNNING are set to RECOVERY_ABORTING. Transactions already RECOVERY_ABORTING are unchanged.

### Redo

Repeats history from the earliest recLSN in the DPT. For each UPDATE or CLR record
encountered (in LSN order), redo the record if and only if:
1. The page is in the DPT.
2. The record's LSN >= the page's recLSN in the DPT.
3. The page's current pageLSN is **strictly less than** the record's LSN.

Redoing a record means applying its `after` value to the page and updating the page's
pageLSN to the record's LSN.

### Undo

Rolls back all RECOVERY_ABORTING transactions. Uses a max-priority-queue of LSNs
(initialized with each such transaction's lastLSN). Repeatedly processes the highest LSN:
- If the record is an UPDATE, it is undoable: restore the page to its `before` value.
- CLR, COMMIT, ABORT, and END records are **not** undoable.
- Determine the next LSN: for CLR records use `undo_next_lsn`; for all others use `prev_lsn`.
- If the next LSN is 0, the transaction is fully undone (end it).
- Otherwise, push the next LSN back onto the priority queue.

## Expected Output (`recovery_output.json`)

A JSON object with these fields:

```json
{
  "analysis_dpt": {"<page_id>": <recLSN>, ...},
  "analysis_txn_table": {
    "<txn_id>": {"status": "<STATUS>", "last_lsn": <LSN>}, ...
  },
  "redo_lsns": [<LSN>, ...],
  "undo_lsns": [<LSN>, ...],
  "final_page_states": {"<page_id>": <value>, ...},
  "committed_txns": [<txn_id>, ...],
  "aborted_txns": [<txn_id>, ...]
}
```

- `analysis_dpt`: The DPT after the analysis phase completes. Keys are page IDs as strings.
- `analysis_txn_table`: The transaction table after analysis completes (only RECOVERY_ABORTING
  transactions remain). Keys are transaction IDs as strings.
- `redo_lsns`: Ordered list of LSNs of records that were actually redone during the redo phase.
- `undo_lsns`: Ordered list of LSNs of records that were actually undone during the undo phase.
- `final_page_states`: Final value of every page referenced in the log, after all three phases.
  Keys are page IDs as strings.
- `committed_txns`: Sorted list of transaction IDs that committed (had COMMIT records).
- `aborted_txns`: Sorted list of transaction IDs that were aborted (had ABORT records).
