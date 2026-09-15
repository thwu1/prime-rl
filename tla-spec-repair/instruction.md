Two TLA+ formal specifications for concurrent lock protocols are at `/app/spec/`:

- `ticket_lock.tla` + `ticket_lock.cfg` — a ticket-based mutual exclusion lock with FIFO wait queue and wake signaling
- `rwlock.tla` + `rwlock.cfg` — a readers-writer lock with writer priority, lock upgrade, and lock downgrade

Both specifications and their TLC configuration files contain defects that prevent successful verification.

Fix and complete both specifications and their configuration files so that SANY parses each module without errors and TLC exhaustively model-checks each with every safety invariant defined in the module — zero errors, zero invariant violations, zero deadlocks.

The TLA+ toolchain is at `/opt/tla2tools.jar`. SANY: `java -cp /opt/tla2tools.jar tla2sany.SANY <module.tla>`. TLC: `java -cp /opt/tla2tools.jar tlc2.TLC -config <cfg> -workers 1 <module.tla>`.