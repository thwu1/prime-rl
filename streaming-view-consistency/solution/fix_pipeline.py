#!/usr/bin/env python3

"""
Diagnose and fix bugs in the streaming reconciliation pipeline.

Reads each pipeline source file, identifies defects through targeted
analysis, and applies fixes. Each fix addresses a specific class of
streaming consistency violation.
"""

import re


def fix_operators():
    """Fix BalanceJoiner.compute: must iterate ALL accounts, not just credits.

    The bug: balance computation iterates only credits.keys(), so accounts
    that have debits but no credits (they sent money but never received any)
    are excluded from the balance dict. Their negative contribution is lost,
    causing sum(balance.values()) != 0.

    The fix: iterate the union of credits and debits keys.
    """
    path = '/app/pipeline/operators.py'
    with open(path) as f:
        source = f.read()

    # Verify the bug exists
    if 'for account in credits:' not in source:
        print(f"SKIP {path}: pattern not found")
        return

    source = source.replace(
        'for account in credits:',
        'for account in set(credits.keys()) | set(debits.keys()):'
    )

    with open(path, 'w') as f:
        f.write(source)
    print(f"FIXED {path}: BalanceJoiner now includes debit-only accounts")


def fix_progress():
    """Fix ProgressTracker.is_late: use strict less-than, not less-or-equal.

    The bug: is_late uses event['ts'] <= self.watermark. This rejects events
    whose timestamp equals the watermark, even though those events are still
    valid (the watermark means 'all events BEFORE this time have arrived',
    not 'at or before'). The fence-post error causes valid data to be dropped.

    The fix: use < instead of <=.
    """
    path = '/app/pipeline/progress.py'
    with open(path) as f:
        source = f.read()

    if "event['ts'] <= self.watermark" not in source:
        print(f"SKIP {path}: pattern not found")
        return

    source = source.replace(
        "return event['ts'] <= self.watermark",
        "return event['ts'] < self.watermark"
    )

    with open(path, 'w') as f:
        f.write(source)
    print(f"FIXED {path}: is_late now uses strict less-than")


def fix_engine_ingest():
    """Fix non-atomic checkpoint in IncrementalViewEngine.ingest.

    The bug: in the ingest method, after draining events from the buffer,
    the credit operator is updated first, then a snapshot is emitted, and
    only then the debit operator is updated. This means the snapshot captures
    credits from the current epoch but debits from the previous epoch —
    a classic 'combining streams without synchronization' failure that
    produces impossible intermediate states (total != 0).

    The fix: process BOTH operators before emitting the snapshot.
    """
    path = '/app/engine.py'
    with open(path) as f:
        source = f.read()

    old_block = (
        "self.credit_op.process(drained)\n"
        "\n"
        "            # Emit consistent snapshot at the new watermark boundary\n"
        "            snapshot = self.emitter.create_snapshot(\n"
        "                new_wm, self.credit_op, self.debit_op, self.joiner\n"
        "            )\n"
        "            self.emitter.store(snapshot)\n"
        "\n"
        "            self.debit_op.process(drained)"
    )

    new_block = (
        "self.credit_op.process(drained)\n"
        "            self.debit_op.process(drained)\n"
        "\n"
        "            # Emit consistent snapshot at the new watermark boundary\n"
        "            snapshot = self.emitter.create_snapshot(\n"
        "                new_wm, self.credit_op, self.debit_op, self.joiner\n"
        "            )\n"
        "            self.emitter.store(snapshot)"
    )

    if old_block not in source:
        print(f"SKIP {path} (ingest): pattern not found")
        return

    source = source.replace(old_block, new_block)

    with open(path, 'w') as f:
        f.write(source)
    print(f"FIXED {path}: operator processing now atomic before snapshot")


def fix_engine_finalize():
    """Fix off-by-one in IncrementalViewEngine.finalize.

    The bug: finalize computes force_advance(max_ts) but force_advance
    drains events with ts < target_wm. This means events at exactly max_ts
    are never drained — they remain in the buffer and are silently lost.

    The fix: use force_advance(max_ts + 1) so all remaining events
    including those at max_ts are drained.
    """
    path = '/app/engine.py'
    with open(path) as f:
        source = f.read()

    if 'self.tracker.force_advance(max_ts)' not in source:
        print(f"SKIP {path} (finalize): pattern not found")
        return

    source = source.replace(
        'self.tracker.force_advance(max_ts)',
        'self.tracker.force_advance(max_ts + 1)'
    )

    with open(path, 'w') as f:
        f.write(source)
    print(f"FIXED {path}: finalize now drains all remaining events")


if __name__ == '__main__':
    fix_operators()
    fix_progress()
    fix_engine_ingest()
    fix_engine_finalize()
    print("\nAll pipeline defects fixed.")
