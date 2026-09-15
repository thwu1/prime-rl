---- MODULE kip966 ----
(**************************************************************************)
(* Kafka KIP-966: Eligible Leader Replicas                                *)
(*                                                                        *)
(* Formal specification of the Kafka partition replication protocol with   *)
(* the KIP-966 extension for handling unclean broker shutdowns without     *)
(* fsync. Models a single partition's state machine.                       *)
(*                                                                        *)
(* Key concepts:                                                          *)
(*   ISR  (In-Sync Replicas) - replication quorum; all members have       *)
(*        replicated up to the high watermark.                            *)
(*   ELR  (Eligible Leader Replicas) - replicas not in ISR but            *)
(*        guaranteed to host all committed data. A replica is added       *)
(*        here when its fencing causes ISR to drop below MinISR AND       *)
(*        the combined ISR+ELR pool is also below MinISR (meaning HWM    *)
(*        is blocked and the replica's data remains complete).            *)
(*   LastKnownELR - replicas that were in ELR but experienced an          *)
(*        unclean shutdown, losing their completeness guarantee. They     *)
(*        MAY still have all committed data.                              *)
(*   HWM  (High Watermark) - committed offset; may only advance when     *)
(*        |ISR| >= MinISR.                                                *)
(*   LEO  (Log End Offset) - number of records in a replica's log.        *)
(*                                                                        *)
(* Leader election follows a strict cascade:                              *)
(*   1. Clean election from ISR (unfenced members)                        *)
(*      -> preserves ISR: keeps all unfenced ISR members                  *)
(*      -> if preserved ISR >= MinISR, clears ELR and LastKnownELR        *)
(*   2. Clean election from ELR (unfenced members)                        *)
(*      -> ISR = {elected}, elected removed from ELR                      *)
(*   3. Recovery (mode-dependent):                                        *)
(*      proactive: ELR non-empty but ALL fenced; pick any unfenced        *)
(*        replica from the full replica set.                              *)
(*        If proactive conditions not met, fall through to balanced.      *)
(*      balanced: ISR empty AND ELR empty; pick from unfenced             *)
(*        LastKnownELR members.                                           *)
(*      manual: no automatic recovery.                                    *)
(*                                                                        *)
(* On any successful election:                                            *)
(*   - data_lost = max(0, old_HWM - elected.LEO)                         *)
(*   - HWM = min(old_HWM, elected.LEO)                                   *)
(*   - All non-leader replicas truncated to min(their_LEO, elected.LEO)   *)
(*                                                                        *)
(* Tiebreaking: among candidates with the highest LEO, select the         *)
(* lexicographically smallest replica name.                               *)
(*                                                                        *)
(* When no candidate is found, the election fails with no state change.   *)
(* An implementation should record each election outcome including type:  *)
(*   "clean"             - elected from ISR or ELR                        *)
(*   "unclean_proactive" - proactive recovery                             *)
(*   "unclean_balanced"  - balanced recovery                              *)
(*   "failed"            - no candidate available                         *)
(*                                                                        *)
(* Adding a caught-up follower to ISR (AddToISR):                         *)
(*   Preconditions: leader exists, replica is unfenced, not the leader,   *)
(*   and replica.LEO >= HWM.                                              *)
(*   When the addition brings |ISR| >= MinISR, ELR and LastKnownELR       *)
(*   are cleared entirely.                                                *)
(**************************************************************************)

EXTENDS Integers, Sequences, FiniteSets

CONSTANTS
    Replicas,       \* Set of replica identifiers, e.g. {"R1", "R2", "R3"}
    MinISR,         \* Minimum ISR size required for HWM advancement
    RecoveryMode,   \* One of: "balanced", "proactive", "manual"
    MaxOffset       \* Upper bound on log offsets (for bounded model checking)

VARIABLES
    leader,         \* Current leader: element of Replicas or "None"
    isr,            \* In-Sync Replicas: subset of Replicas
    elr,            \* Eligible Leader Replicas: subset of Replicas
    lkelr,          \* LastKnownELR: subset of Replicas
    fencedSet,      \* Set of fenced (offline/unreachable) replicas
    replicaLEO,     \* Function [Replicas -> 0..MaxOffset]: Log End Offset
    highWatermark,  \* High Watermark (committed offset)
    cumulDataLost   \* Cumulative committed data lost across all elections

vars == <<leader, isr, elr, lkelr, fencedSet, replicaLEO, highWatermark, cumulDataLost>>

(**************************************************************************)
(* Helper operators                                                       *)
(**************************************************************************)

\* Minimum of a non-empty set of integers
SetMin(S) == CHOOSE x \in S : \A y \in S : x <= y

\* Maximum of a non-empty set of integers
SetMax(S) == CHOOSE x \in S : \A y \in S : x >= y

\* Minimum LEO across a set of replicas
MinReplicaLEO(S) == SetMin({replicaLEO[r] : r \in S})

\* Maximum LEO across a set of replicas
MaxReplicaLEO(S) == SetMax({replicaLEO[r] : r \in S})

\* Lexicographically smallest element of a non-empty set
LexSmallest(S) == CHOOSE r \in S : \A s \in S : r <= s

\* Best candidate for election: highest LEO, ties broken lexicographically
BestCandidate(S) ==
    LET maxL == MaxReplicaLEO(S)
        topSet == {r \in S : replicaLEO[r] = maxL}
    IN LexSmallest(topSet)

(**************************************************************************)
(* Initial state                                                          *)
(* Leader is the lexicographically smallest replica (e.g., R1).           *)
(* All replicas start in ISR with LEO=0 and HWM=0.                       *)
(**************************************************************************)

Init ==
    /\ leader = LexSmallest(Replicas)
    /\ isr = Replicas
    /\ elr = {}
    /\ lkelr = {}
    /\ fencedSet = {}
    /\ replicaLEO = [r \in Replicas |-> 0]
    /\ highWatermark = 0
    /\ cumulDataLost = 0

(**************************************************************************)
(* Actions                                                                *)
(**************************************************************************)

(* ---- Produce ----
   Leader appends `count` records to its log. Only the leader's LEO
   changes; followers are not affected until they fetch (Replicate).     *)
Produce(count) ==
    /\ leader # "None"
    /\ count > 0
    /\ replicaLEO[leader] + count <= MaxOffset
    /\ replicaLEO' = [replicaLEO EXCEPT ![leader] = @ + count]
    /\ UNCHANGED <<leader, isr, elr, lkelr, fencedSet, highWatermark, cumulDataLost>>

(* ---- Replicate ----
   An unfenced non-leader replica fetches from the leader up to the
   leader's LEO (full replication). If the replica's LEO exceeds the
   leader's LEO, it is first truncated (divergent log suffix removal),
   then advanced to the target.                                          *)
Replicate(r) ==
    /\ leader # "None"
    /\ r # leader
    /\ r \notin fencedSet
    /\ LET leaderL == replicaLEO[leader]
           truncated == IF replicaLEO[r] > leaderL THEN leaderL ELSE replicaLEO[r]
           newLEO == IF truncated < leaderL THEN leaderL ELSE truncated
       IN replicaLEO' = [replicaLEO EXCEPT ![r] = newLEO]
    /\ UNCHANGED <<leader, isr, elr, lkelr, fencedSet, highWatermark, cumulDataLost>>

(* ---- ReplicateUpTo ----
   Partial replication: follower fetches up to min(upTo, leader.LEO).
   Same truncation semantics as full Replicate.                          *)
ReplicateUpTo(r, upTo) ==
    /\ leader # "None"
    /\ r # leader
    /\ r \notin fencedSet
    /\ upTo >= 0
    /\ LET leaderL == replicaLEO[leader]
           target == IF upTo < leaderL THEN upTo ELSE leaderL
           truncated == IF replicaLEO[r] > leaderL THEN leaderL ELSE replicaLEO[r]
           newLEO == IF truncated < target THEN target ELSE truncated
       IN replicaLEO' = [replicaLEO EXCEPT ![r] = newLEO]
    /\ UNCHANGED <<leader, isr, elr, lkelr, fencedSet, highWatermark, cumulDataLost>>

(* ---- AdvanceHWM ----
   Leader advances the high watermark to the minimum LEO across all ISR
   members, but ONLY when |ISR| >= MinISR. When ISR is too small, HWM
   is blocked -- this is the key safety property that enables ELR.       *)
AdvanceHWM ==
    /\ leader # "None"
    /\ Cardinality(isr) >= MinISR
    /\ LET minL == MinReplicaLEO(isr)
           newHWM == IF minL > highWatermark THEN minL ELSE highWatermark
       IN highWatermark' = newHWM
    /\ UNCHANGED <<leader, isr, elr, lkelr, fencedSet, replicaLEO, cumulDataLost>>

(* ---- Fence ----
   Controller marks a replica as fenced (offline/unreachable).

   1. Replica is removed from ISR.
   2. If the replica was leader, leadership is vacated (leader = "None").
   3. ELR addition: if after removal |ISR| < MinISR AND the combined
      |ISR| + |ELR| is also < MinISR, add the fenced replica to ELR.
      This preserves the leader candidate pool: since HWM cannot advance,
      this replica's data remains complete (all records up to current HWM).

   Note: the ELR addition checks the CURRENT ELR size (before adding),
   not the size after adding.                                            *)
Fence(r) ==
    /\ r \in Replicas
    /\ r \notin fencedSet
    /\ LET wasLeader == (r = leader)
           newISR == isr \ {r}
           newLeader == IF wasLeader THEN "None" ELSE leader
           shouldAddELR == Cardinality(newISR) < MinISR
                           /\ Cardinality(newISR) + Cardinality(elr) < MinISR
           newELR == IF shouldAddELR THEN elr \cup {r} ELSE elr
       IN /\ leader' = newLeader
          /\ isr' = newISR
          /\ elr' = newELR
          /\ fencedSet' = fencedSet \cup {r}
    /\ UNCHANGED <<lkelr, replicaLEO, highWatermark, cumulDataLost>>

(* ---- UnfenceClean ----
   Replica comes back online after a clean shutdown. No data loss.
   No changes to ELR/LastKnownELR membership.                           *)
UnfenceClean(r) ==
    /\ r \in fencedSet
    /\ fencedSet' = fencedSet \ {r}
    /\ UNCHANGED <<leader, isr, elr, lkelr, replicaLEO, highWatermark, cumulDataLost>>

(* ---- UnfenceUnclean ----
   Replica comes back online after an unclean shutdown (OS crash, power
   loss, etc.). May have lost unflushed records.

   If records were lost, the replica's LEO is reduced (minimum 0).
   If the replica was in ELR, it loses its completeness guarantee and
   is moved to LastKnownELR (it may still be complete, but this is
   no longer guaranteed).                                                *)
UnfenceUnclean(r, recordsLost) ==
    /\ r \in fencedSet
    /\ recordsLost >= 0
    /\ fencedSet' = fencedSet \ {r}
    /\ LET currentLEO == replicaLEO[r]
           newLEO == IF recordsLost > 0
                     THEN IF currentLEO >= recordsLost
                          THEN currentLEO - recordsLost
                          ELSE 0
                     ELSE currentLEO
       IN replicaLEO' = [replicaLEO EXCEPT ![r] = newLEO]
    /\ IF r \in elr
       THEN /\ elr' = elr \ {r}
            /\ lkelr' = lkelr \cup {r}
       ELSE UNCHANGED <<elr, lkelr>>
    /\ UNCHANGED <<leader, isr, highWatermark, cumulDataLost>>

(* ---- ElectLeader ----
   Controller attempts to elect a new leader for a leaderless partition.
   Precondition: leader = "None" (no current leader).

   See module header for the full election cascade description.          *)

\* Helper: apply post-election state changes common to all election types
DoElection(elected, newISR, newELR, newLKELR) ==
    LET oldHWM == highWatermark
        loss == IF oldHWM > replicaLEO[elected]
                THEN oldHWM - replicaLEO[elected]
                ELSE 0
        newHWM == IF replicaLEO[elected] < oldHWM
                  THEN replicaLEO[elected]
                  ELSE oldHWM
        electedLEO == replicaLEO[elected]
    IN /\ leader' = elected
       /\ highWatermark' = newHWM
       /\ cumulDataLost' = cumulDataLost + loss
       /\ isr' = newISR
       /\ elr' = newELR
       /\ lkelr' = newLKELR
       /\ replicaLEO' = [r \in Replicas |->
            IF r = elected THEN replicaLEO[r]
            ELSE IF replicaLEO[r] > electedLEO THEN electedLEO
            ELSE replicaLEO[r]]
       /\ UNCHANGED fencedSet

ElectLeader ==
    /\ leader = "None"
    /\ LET
        \* Step 1: Clean election from ISR
        isrCands == {r \in isr : r \notin fencedSet}

        \* Step 2: Clean election from ELR
        elrCands == {r \in elr : r \notin fencedSet}

        \* Step 3a: Proactive recovery conditions
        proactiveOK == RecoveryMode = "proactive"
                       /\ elr # {}
                       /\ \A r \in elr : r \in fencedSet
        proactiveCands == {r \in Replicas : r \notin fencedSet}

        \* Step 3b: Balanced recovery conditions (also fallback for proactive)
        balancedOK == RecoveryMode \in {"balanced", "proactive"}
                      /\ isr = {}
                      /\ elr = {}
                      /\ lkelr # {}
        balancedCands == {r \in lkelr : r \notin fencedSet}
       IN
        IF isrCands # {} THEN
            \* Clean election from ISR: preserve ISR membership
            LET elected == BestCandidate(isrCands)
                preservedISR == {r \in isr : r \notin fencedSet}
                clearSets == Cardinality(preservedISR) >= MinISR
            IN DoElection(elected, preservedISR,
                          IF clearSets THEN {} ELSE elr,
                          IF clearSets THEN {} ELSE lkelr)
        ELSE IF elrCands # {} THEN
            \* Clean election from ELR
            LET elected == BestCandidate(elrCands)
            IN DoElection(elected, {elected}, elr \ {elected}, lkelr)
        ELSE IF proactiveOK /\ proactiveCands # {} THEN
            \* Proactive recovery: pick from any unfenced replica
            LET elected == BestCandidate(proactiveCands)
            IN DoElection(elected, {elected},
                          elr \ {elected}, lkelr \ {elected})
        ELSE IF balancedOK /\ balancedCands # {} THEN
            \* Balanced recovery: pick from unfenced LastKnownELR
            LET elected == BestCandidate(balancedCands)
            IN DoElection(elected, {elected},
                          elr \ {elected}, lkelr \ {elected})
        ELSE
            \* No candidate found: election fails, no state change
            UNCHANGED vars

(* ---- AddToISR ----
   Leader adds a caught-up follower replica to the ISR.

   Preconditions: leader exists, replica is not the leader, replica is
   unfenced, and replica.LEO >= HWM.

   When this addition brings |ISR| >= MinISR, the ELR and LastKnownELR
   are cleared entirely -- the frozen candidate pool is no longer needed
   because HWM can advance again.                                       *)
AddToISR(r) ==
    /\ leader # "None"
    /\ r # leader
    /\ r \notin fencedSet
    /\ replicaLEO[r] >= highWatermark
    /\ LET newISR == isr \cup {r}
           clearSets == Cardinality(newISR) >= MinISR
       IN /\ isr' = newISR
          /\ IF clearSets
             THEN /\ elr' = {}
                  /\ lkelr' = {}
             ELSE UNCHANGED <<elr, lkelr>>
    /\ UNCHANGED <<leader, fencedSet, replicaLEO, highWatermark, cumulDataLost>>

(**************************************************************************)
(* Specification                                                          *)
(**************************************************************************)

Next ==
    \/ \E count \in 1..MaxOffset : Produce(count)
    \/ \E r \in Replicas : Replicate(r)
    \/ \E r \in Replicas : \E upTo \in 0..MaxOffset : ReplicateUpTo(r, upTo)
    \/ AdvanceHWM
    \/ \E r \in Replicas : Fence(r)
    \/ \E r \in Replicas : UnfenceClean(r)
    \/ \E r \in Replicas :
        \E lost \in 0..MaxOffset : UnfenceUnclean(r, lost)
    \/ ElectLeader
    \/ \E r \in Replicas : AddToISR(r)

Spec == Init /\ [][Next]_vars

(**************************************************************************)
(* Safety invariants                                                      *)
(**************************************************************************)

\* Type correctness
TypeOK ==
    /\ leader \in Replicas \cup {"None"}
    /\ isr \subseteq Replicas
    /\ elr \subseteq Replicas
    /\ lkelr \subseteq Replicas
    /\ fencedSet \subseteq Replicas
    /\ replicaLEO \in [Replicas -> 0..MaxOffset]
    /\ highWatermark \in 0..MaxOffset
    /\ cumulDataLost \in Nat

\* ISR, ELR, and LastKnownELR must be pairwise disjoint
SetsDisjoint ==
    /\ isr \cap elr = {}
    /\ isr \cap lkelr = {}
    /\ elr \cap lkelr = {}

\* If a leader exists, it must be an unfenced ISR member
LeaderValid ==
    leader # "None" =>
        /\ leader \in isr
        /\ leader \notin fencedSet

\* HWM never exceeds any ISR member's LEO when a leader exists
HWMSafe ==
    leader # "None" => \A r \in isr : replicaLEO[r] >= highWatermark

====
