#!/usr/bin/env python3
"""
Fix and complete both TLA+ lock specifications.

"""

TICKET_SPEC = "/app/spec/ticket_lock.tla"
TICKET_CFG = "/app/spec/ticket_lock.cfg"
RWLOCK_SPEC = "/app/spec/rwlock.tla"
RWLOCK_CFG = "/app/spec/rwlock.cfg"


def fix_ticket_lock():
    with open(TICKET_SPEC, "r") as f:
        spec = f.read()

    # Add Sequences to EXTENDS (needed for Append, Head, Tail, Len)
    spec = spec.replace(
        "EXTENDS Naturals, FiniteSets, TLC",
        "EXTENDS Naturals, Sequences, FiniteSets, TLC",
    )

    # Replace unbounded CHOOSE with CONSTANT declaration
    spec = spec.replace(
        "CONSTANTS Nodes\n\nNil == CHOOSE v : v \\notin Nodes",
        "CONSTANTS Nodes, Nil",
    )

    # Fix typo in AwaitWake: queu -> queue
    spec = spec.replace("queu>>", "queue>>")

    # Fix ReleaseLock: must clear holder when releasing the lock.
    # Without this, after ReleaseLock + WakeNext the node reaches "Idle"
    # state but holder still references it, violating NoStaleHolder.
    spec = spec.replace(
        "    /\\ locked' = FALSE\n"
        "    /\\ pc' = [pc EXCEPT ![n] = \"Waking\"]\n"
        "    /\\ UNCHANGED <<holder, queue, woken>>",

        "    /\\ locked' = FALSE\n"
        "    /\\ holder' = Nil\n"
        "    /\\ pc' = [pc EXCEPT ![n] = \"Waking\"]\n"
        "    /\\ UNCHANGED <<queue, woken>>",
    )

    with open(TICKET_SPEC, "w") as f:
        f.write(spec)
    print(f"Fixed {TICKET_SPEC}")


def fix_ticket_lock_config():
    config = """\
SPECIFICATION Specification

CONSTANTS
    Nodes = {n1, n2, n3}
    Nil = n0

INVARIANT
    MutualExclusion
    HolderConsistency
    QueueValidity
    NoStaleHolder

CONSTRAINT
    StateConstraint
"""
    with open(TICKET_CFG, "w") as f:
        f.write(config)
    print(f"Fixed {TICKET_CFG}")


def fix_rwlock():
    with open(RWLOCK_SPEC, "r") as f:
        spec = f.read()

    # Add Sequences to EXTENDS
    spec = spec.replace(
        "EXTENDS Naturals, FiniteSets, TLC",
        "EXTENDS Naturals, Sequences, FiniteSets, TLC",
    )

    # Replace unbounded CHOOSE with CONSTANT declaration
    spec = spec.replace(
        "CONSTANTS Nodes\n\nNil == CHOOSE v : v \\notin Nodes",
        "CONSTANTS Nodes, Nil",
    )

    # Fix DowngradeToRead: must set writer' = Nil when downgrading.
    # Without this, after downgrade pc moves to "Reading" but writer still
    # references the node, violating WriterTracking.
    spec = spec.replace(
        "    /\\ writer = n\n"
        "    /\\ readers' = readers \\union {n}\n"
        "    /\\ pc' = [pc EXCEPT ![n] = \"Reading\"]\n"
        "    /\\ UNCHANGED <<writer, writerQueue, upgrader>>",

        "    /\\ writer = n\n"
        "    /\\ writer' = Nil\n"
        "    /\\ readers' = readers \\union {n}\n"
        "    /\\ pc' = [pc EXCEPT ![n] = \"Reading\"]\n"
        "    /\\ UNCHANGED <<writerQueue, upgrader>>",
    )

    # Implement UpgradeToWrite: a reader claims the single upgrade slot
    # and transitions to "Upgrading". The node stays in readers until
    # CompleteUpgrade removes it.
    spec = spec.replace(
        "UpgradeToWrite(n) ==\n"
        "    /\\ FALSE  \\* STUB \u2014 implement this action",

        "UpgradeToWrite(n) ==\n"
        "    /\\ pc[n] = \"Reading\"\n"
        "    /\\ upgrader = Nil\n"
        "    /\\ upgrader' = n\n"
        "    /\\ pc' = [pc EXCEPT ![n] = \"Upgrading\"]\n"
        "    /\\ UNCHANGED <<readers, writer, writerQueue>>",
    )

    # Implement CompleteUpgrade: the upgrader must be the sole reader with
    # no active writer. It atomically leaves readers, becomes writer, and
    # clears the upgrade slot.
    spec = spec.replace(
        "CompleteUpgrade(n) ==\n"
        "    /\\ FALSE  \\* STUB \u2014 implement this action",

        "CompleteUpgrade(n) ==\n"
        "    /\\ pc[n] = \"Upgrading\"\n"
        "    /\\ upgrader = n\n"
        "    /\\ readers = {n}\n"
        "    /\\ writer = Nil\n"
        "    /\\ readers' = {}\n"
        "    /\\ writer' = n\n"
        "    /\\ upgrader' = Nil\n"
        "    /\\ pc' = [pc EXCEPT ![n] = \"Writing\"]\n"
        "    /\\ UNCHANGED <<writerQueue>>",
    )

    # Implement UpgradeSafety invariant: when upgrader is non-Nil,
    # the upgrader must be in readers with pc = "Upgrading".
    spec = spec.replace(
        "UpgradeSafety ==\n"
        "    TRUE  \\* STUB \u2014 implement this invariant",

        "UpgradeSafety ==\n"
        "    upgrader /= Nil => (upgrader \\in readers /\\ pc[upgrader] = \"Upgrading\")",
    )

    with open(RWLOCK_SPEC, "w") as f:
        f.write(spec)
    print(f"Fixed {RWLOCK_SPEC}")


def fix_rwlock_config():
    config = """\
SPECIFICATION Specification

CONSTANTS
    Nodes = {n1, n2, n3}
    Nil = n0

INVARIANT
    NoReadWriteConflict
    SingleWriter
    QueueIntegrity
    UpgradeSafety
    WriterTracking

CONSTRAINT
    StateConstraint
"""
    with open(RWLOCK_CFG, "w") as f:
        f.write(config)
    print(f"Fixed {RWLOCK_CFG}")


if __name__ == "__main__":
    fix_ticket_lock()
    fix_ticket_lock_config()
    fix_rwlock()
    fix_rwlock_config()
    print("All fixes applied.")
