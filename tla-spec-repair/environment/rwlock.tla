---- MODULE rwlock ----
EXTENDS Naturals, FiniteSets, TLC

\* Readers-writer lock with writer priority, lock upgrade, and lock downgrade.
\* Models N nodes competing for shared (read) or exclusive (write) access
\* to a resource, with FIFO ordering for exclusive requests and a single-slot
\* upgrade path allowing a reader to atomically become a writer.

CONSTANTS Nodes

Nil == CHOOSE v : v \notin Nodes

VARIABLES pc, readers, writer, writerQueue, upgrader

vars == <<pc, readers, writer, writerQueue, upgrader>>

Init ==
    /\ pc = [n \in Nodes |-> "Idle"]
    /\ readers = {}
    /\ writer = Nil
    /\ writerQueue = <<>>
    /\ upgrader = Nil

----

\* Node acquires shared (read) access — immediate if no writer/upgrader/pending writers
AcquireRead(n) ==
    /\ pc[n] = "Idle"
    /\ writer = Nil
    /\ upgrader = Nil
    /\ writerQueue = <<>>
    /\ readers' = readers \union {n}
    /\ pc' = [pc EXCEPT ![n] = "Reading"]
    /\ UNCHANGED <<writer, writerQueue, upgrader>>

\* Node requests exclusive (write) access — enters FIFO wait queue
RequestWrite(n) ==
    /\ pc[n] = "Idle"
    /\ pc' = [pc EXCEPT ![n] = "WaitWrite"]
    /\ writerQueue' = Append(writerQueue, n)
    /\ UNCHANGED <<readers, writer, upgrader>>

\* Head-of-queue writer is granted exclusive access when resource is fully free
GrantWrite(n) ==
    /\ pc[n] = "WaitWrite"
    /\ writer = Nil
    /\ readers = {}
    /\ Len(writerQueue) > 0
    /\ Head(writerQueue) = n
    /\ writer' = n
    /\ writerQueue' = Tail(writerQueue)
    /\ pc' = [pc EXCEPT ![n] = "Writing"]
    /\ UNCHANGED <<readers, upgrader>>

\* --- Upgrade path: reader -> writer ---

\* A reading node requests to upgrade to exclusive (write) access.
\* Only one upgrade may be in progress at a time. The upgrading node
\* remains in the readers set until CompleteUpgrade. Transitions from
\* "Reading" to "Upgrading" pc state.
UpgradeToWrite(n) ==
    /\ FALSE  \* STUB — implement this action

\* Completes a pending upgrade: the upgrading node becomes the writer.
\* The upgrader must be the sole remaining reader with no active writer.
\* Removes the node from readers, sets it as writer, clears the upgrader
\* slot, and transitions to "Writing" pc state.
CompleteUpgrade(n) ==
    /\ FALSE  \* STUB — implement this action

\* --- Downgrade path: writer -> reader ---

\* Writer downgrades to shared (read) access
DowngradeToRead(n) ==
    /\ pc[n] = "Writing"
    /\ writer = n
    /\ readers' = readers \union {n}
    /\ pc' = [pc EXCEPT ![n] = "Reading"]
    /\ UNCHANGED <<writer, writerQueue, upgrader>>

\* Release shared (read) lock
ReleaseRead(n) ==
    /\ pc[n] = "Reading"
    /\ readers' = readers \ {n}
    /\ pc' = [pc EXCEPT ![n] = "Idle"]
    /\ UNCHANGED <<writer, writerQueue, upgrader>>

\* Release exclusive (write) lock
ReleaseWrite(n) ==
    /\ pc[n] = "Writing"
    /\ writer = n
    /\ writer' = Nil
    /\ pc' = [pc EXCEPT ![n] = "Idle"]
    /\ UNCHANGED <<readers, writerQueue, upgrader>>

\* Cancel a pending upgrade and return to reading
CancelUpgrade(n) ==
    /\ pc[n] = "Upgrading"
    /\ upgrader = n
    /\ upgrader' = Nil
    /\ pc' = [pc EXCEPT ![n] = "Reading"]
    /\ UNCHANGED <<readers, writer, writerQueue>>

\* Stuttering step when all nodes are idle
Terminating ==
    /\ \A n \in Nodes : pc[n] = "Idle"
    /\ UNCHANGED vars

----

Next ==
    \/ \E n \in Nodes :
        \/ AcquireRead(n)
        \/ RequestWrite(n)
        \/ GrantWrite(n)
        \/ UpgradeToWrite(n)
        \/ CompleteUpgrade(n)
        \/ DowngradeToRead(n)
        \/ ReleaseRead(n)
        \/ ReleaseWrite(n)
        \/ CancelUpgrade(n)
    \/ Terminating

Specification == Init /\ [][Next]_vars

----

\* SAFETY: No simultaneous readers and writer
NoReadWriteConflict ==
    writer /= Nil => readers = {}

\* SAFETY: At most one writer at a time
SingleWriter ==
    Cardinality({n \in Nodes : pc[n] = "Writing"}) <= 1

\* SAFETY: Every node in the writer wait queue is in WaitWrite state
QueueIntegrity ==
    \A i \in 1..Len(writerQueue) :
        pc[writerQueue[i]] = "WaitWrite"

\* SAFETY: When an upgrade is in progress, the upgrading node is
\* a member of the readers set and its pc is "Upgrading".
UpgradeSafety ==
    TRUE  \* STUB — implement this invariant

\* SAFETY: Writer variable accurately tracks the writing node
WriterTracking ==
    (writer /= Nil) => pc[writer] = "Writing"

\* State constraint for bounded model checking
StateConstraint ==
    Len(writerQueue) <= Cardinality(Nodes)

====
