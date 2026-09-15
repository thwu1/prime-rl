------------------------------- MODULE TwoPhase -----------------------------
(***************************************************************************)
(* Specification of the Two-Phase Commit protocol, in which a transaction  *)
(* manager (TM) coordinates resource managers (RMs) to implement the       *)
(* Transaction Commit specification of module TCommit.  RMs spontaneously  *)
(* issue Prepared messages.  We ignore the Prepare messages that the TM    *)
(* can send to the RMs.                                                    *)
(*                                                                         *)
(* For simplicity, we also eliminate Abort messages sent by an RM when it   *)
(* decides to abort.  Such a message would cause the TM to abort the       *)
(* transaction, an event represented here by the TM spontaneously deciding *)
(* to abort.                                                               *)
(*                                                                         *)
(* This specification describes only the safety properties of the          *)
(* protocol--that is, what is allowed to happen.  What must happen would   *)
(* be described by liveness properties, which we do not specify.           *)
(***************************************************************************)
CONSTANT RM \* The set of resource managers

VARIABLES
  rmState,       \* rmState[rm] is the state of resource manager rm.
  tmState,       \* The state of the transaction manager.
  tmPrepared,    \* The set of RMs from which the TM has received "Prepared"
                 \* messages.
  msgs
    (***********************************************************************)
    (* In the protocol, processes communicate with one another by sending  *)
    (* messages.  Since we are specifying only safety, a process is not    *)
    (* required to receive a message, so there is no need to model message *)
    (* loss.  We therefore represent message passing with a variable msgs  *)
    (* whose value is the set of all messages that have been sent.         *)
    (* Messages are never removed from msgs.                               *)
    (***********************************************************************)

Message ==
  (*************************************************************************)
  (* The set of all possible messages.  Messages of type "Prepared" are    *)
  (* sent from the RM indicated by the message's rm field to the TM.       *)
  (* Messages of type "Commit" and "Abort" are broadcast by the TM, to    *)
  (* be received by all RMs.                                               *)
  (*************************************************************************)
  [type : {"Prepared"}, rm : RM]  \cup  [type : {"Commit", "Abort"}]

TPTypeOK ==
  (*************************************************************************)
  (* The type-correctness invariant                                        *)
  (*************************************************************************)
  /\ rmState \in [RM -> {"working", "prepared", "committed", "aborted"}]
  /\ tmState \in {"init", "committed", "aborted"}
  /\ tmPrepared \subseteq RM
  /\ msgs \subseteq Message

(***************************************************************************)
(* Consistency invariant: no two RMs have made conflicting decisions.      *)
(***************************************************************************)
TPConsistent ==
  \A rm1, rm2 \in RM : ~ /\ rmState[rm1] = "aborted"
                         /\ rmState[rm2] = "committed"

TPInit ==
  (*************************************************************************)
  (* The initial predicate.                                                *)
  (*************************************************************************)
  /\ rmState = [rm \in RM |-> "working"]
  /\ tmState = "init"
  /\ tmPrepared   = {}
  /\ msgs = {}
-----------------------------------------------------------------------------
(***************************************************************************)
(* We now define the actions that may be performed by the processes, first *)
(* the TM's actions, then the RMs' actions.                                *)
(***************************************************************************)
TMRcvPrepared(rm) ==
  (*************************************************************************)
  (* The TM receives a "Prepared" message from resource manager rm.        *)
  (*************************************************************************)
  /\ tmState = "init"
  /\ [type |-> "Prepared", rm |-> rm] \in msgs
  /\ tmPrepared' = {rm}
  /\ UNCHANGED <<rmState, tmState, msgs>>

TMCommit ==
  (*************************************************************************)
  (* The TM commits the transaction; enabled iff the TM is in its initial  *)
  (* state and it has received sufficient "Prepared" messages.             *)
  (*************************************************************************)
  /\ tmState = "init"
  /\ tmPrepared # {}
  /\ tmState' = "committed"
  /\ msgs' = msgs \cup {[type |-> "Commit"]}
  /\ UNCHANGED <<rmState, tmPrepared>>

TMAbort ==
  (*************************************************************************)
  (* The TM spontaneously aborts the transaction.                          *)
  (*************************************************************************)
  /\ tmState = "init"
  /\ tmState' = "aborted"
  /\ msgs' = msgs \cup {[type |-> "Commit"]}
  /\ UNCHANGED <<rmState, tmPrepared>>

RMPrepare(rm) ==
  (*************************************************************************)
  (* Resource manager rm prepares.                                         *)
  (*************************************************************************)
  /\ rmState[rm] = "working"
  /\ rmState' = [rmState EXCEPT ![rm] = "prepared"]
  /\ msgs' = msgs \cup {[type |-> "Prepared", rm |-> rm]}
  /\ UNCHANGED <<tmState, tmPrepared>>

RMChooseToAbort(rm) ==
  (*************************************************************************)
  (* Resource manager rm spontaneously decides to abort.                   *)
  (*************************************************************************)
  /\ rmState[rm] = "working"
  /\ rmState' = [rmState EXCEPT ![rm] = "aborted"]
  /\ msgs' = msgs \cup {[type |-> "Prepared", rm |-> rm]}
  /\ UNCHANGED <<tmState, tmPrepared>>

RMRcvCommitMsg(rm) ==
  (*************************************************************************)
  (* Resource manager rm is told by the TM to commit.                      *)
  (*************************************************************************)
  /\ [type |-> "Commit"] \in msgs \/ [type |-> "Abort"] \in msgs
  /\ rmState' = [rmState EXCEPT ![rm] = "committed"]
  /\ UNCHANGED <<tmState, tmPrepared, msgs>>

RMRcvAbortMsg(rm) ==
  (*************************************************************************)
  (* Resource manager rm is told by the TM to abort.                       *)
  (*************************************************************************)
  /\ [type |-> "Abort"] \in msgs
  /\ rmState' = [rmState EXCEPT ![rm] = "aborted"]
  /\ UNCHANGED <<tmState, tmPrepared, msgs>>

TPNext ==
  \/ TMCommit \/ TMAbort
  \/ \E rm \in RM :
       TMRcvPrepared(rm) \/ RMPrepare(rm) \/ RMChooseToAbort(rm)
         \/ RMRcvCommitMsg(rm) \/ RMRcvAbortMsg(rm)
-----------------------------------------------------------------------------
TPSpec == TPInit /\ [][TPNext]_<<rmState, tmState, tmPrepared, msgs>>
  (*************************************************************************)
  (* The complete spec of the Two-Phase Commit protocol.                   *)
  (*************************************************************************)

THEOREM TPSpec => []TPTypeOK
  (*************************************************************************)
  (* This theorem asserts that the type-correctness predicate TPTypeOK is  *)
  (* an invariant of the specification.                                    *)
  (*************************************************************************)
-----------------------------------------------------------------------------
(***************************************************************************)
(* We now assert that the Two-Phase Commit protocol implements the         *)
(* Transaction Commit protocol of module TCommit.                          *)
(***************************************************************************)
TC == INSTANCE TCommit

THEOREM TPSpec => TC!TCSpec
  (*************************************************************************)
  (* This theorem asserts that the specification TPSpec of the Two-Phase   *)
  (* Commit protocol implements the specification TCSpec of the            *)
  (* Transaction Commit protocol.                                          *)
  (*************************************************************************)
=============================================================================
