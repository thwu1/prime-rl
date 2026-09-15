---- MODULE ticket_lock ----
EXTENDS Naturals, FiniteSets, TLC

\* Ticket-based mutex protocol with FIFO wait queue and wake signaling.
\* Models lock acquisition, wait-queue management, and wake-up delivery
\* for a set of competing nodes.

CONSTANTS Nodes

Nil == CHOOSE v : v \notin Nodes

VARIABLES pc, locked, holder, queue, woken

vars == <<pc, locked, holder, queue, woken>>

Init ==
    /\ pc = [n \in Nodes |-> "Idle"]
    /\ locked = FALSE
    /\ holder = Nil
    /\ queue = <<>>
    /\ woken = [n \in Nodes |-> FALSE]

----

\* Node begins trying to acquire the lock
StartLock(n) ==
    /\ pc[n] = "Idle"
    /\ pc' = [pc EXCEPT ![n] = "TryLock"]
    /\ UNCHANGED <<locked, holder, queue, woken>>

\* Node successfully acquires the lock (lock was free)
AcquireLock(n) ==
    /\ pc[n] = "TryLock"
    /\ locked = FALSE
    /\ locked' = TRUE
    /\ holder' = n
    /\ pc' = [pc EXCEPT ![n] = "InCS"]
    /\ UNCHANGED <<queue, woken>>

\* Node fails to acquire (lock is held), will enqueue
FailLock(n) ==
    /\ pc[n] = "TryLock"
    /\ locked = TRUE
    /\ pc' = [pc EXCEPT ![n] = "Enqueue"]
    /\ UNCHANGED <<locked, holder, queue, woken>>

\* Node adds itself to the wait queue
EnqueueSelf(n) ==
    /\ pc[n] = "Enqueue"
    /\ queue' = Append(queue, n)
    /\ pc' = [pc EXCEPT ![n] = "Waiting"]
    /\ UNCHANGED <<locked, holder, woken>>

\* Node receives wake signal and retries lock acquisition
AwaitWake(n) ==
    /\ pc[n] = "Waiting"
    /\ woken[n] = TRUE
    /\ woken' = [woken EXCEPT ![n] = FALSE]
    /\ pc' = [pc EXCEPT ![n] = "TryLock"]
    /\ UNCHANGED <<locked, holder, queu>>

\* Node in critical section begins unlock procedure
BeginUnlock(n) ==
    /\ pc[n] = "InCS"
    /\ pc' = [pc EXCEPT ![n] = "Unlocking"]
    /\ UNCHANGED <<locked, holder, queue, woken>>

\* Node releases the lock
ReleaseLock(n) ==
    /\ pc[n] = "Unlocking"
    /\ holder = n
    /\ locked' = FALSE
    /\ pc' = [pc EXCEPT ![n] = "Waking"]
    /\ UNCHANGED <<holder, queue, woken>>

\* Node wakes the next waiter (FIFO order) then returns to idle
WakeNext(n) ==
    /\ pc[n] = "Waking"
    /\ IF Len(queue) > 0
       THEN LET target == Head(queue)
            IN /\ woken' = [woken EXCEPT ![target] = TRUE]
               /\ queue' = Tail(queue)
               /\ pc' = [pc EXCEPT ![n] = "Idle"]
       ELSE /\ pc' = [pc EXCEPT ![n] = "Idle"]
            /\ UNCHANGED <<queue, woken>>
    /\ UNCHANGED <<locked, holder>>

\* Stuttering step when all nodes are idle
Terminating ==
    /\ \A n \in Nodes : pc[n] = "Idle"
    /\ UNCHANGED vars

----

Next ==
    \/ \E n \in Nodes :
        \/ StartLock(n)
        \/ AcquireLock(n)
        \/ FailLock(n)
        \/ EnqueueSelf(n)
        \/ AwaitWake(n)
        \/ BeginUnlock(n)
        \/ ReleaseLock(n)
        \/ WakeNext(n)
    \/ Terminating

Specification == Init /\ [][Next]_vars

----

\* SAFETY: At most one node in critical section
MutualExclusion ==
    Cardinality({n \in Nodes : pc[n] = "InCS"}) <= 1

\* SAFETY: Lock holder matches node state
HolderConsistency ==
    \A n \in Nodes :
        (pc[n] \in {"InCS", "Unlocking"}) => holder = n

\* SAFETY: All queued nodes are in Waiting state
QueueValidity ==
    \A i \in 1..Len(queue) :
        pc[queue[i]] = "Waiting"

\* SAFETY: Non-nil holder must be in an active lock phase
NoStaleHolder ==
    (holder /= Nil) => pc[holder] \in {"InCS", "Unlocking", "Waking"}

\* State constraint for bounded model checking
StateConstraint ==
    Len(queue) <= Cardinality(Nodes)

====
