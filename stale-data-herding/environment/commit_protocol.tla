---- MODULE commit_protocol ----
EXTENDS Integers, FiniteSets, TLC

(***************************************************************************)
(* Two-Phase Commit protocol specification in PlusCal.                     *)
(* A coordinator orchestrates atomic commitment across participants.       *)
(* Each participant votes yes (prepared) or no (abort).                    *)
(* The coordinator collects votes and broadcasts a commit/abort decision.  *)
(***************************************************************************)

CONSTANTS Participants

(* --algorithm TwoPhaseCommit {
    variables
        pState = [p \in Participants |-> "working"],
        cState = "init",
        yesVotes = {},
        noVotes = {},
        prepSent = {},
        decisionSent = {};

    define {
        TypeOK ==
            /\ pState \in [Participants -> {"working", "prepared", "committed", "aborted"}]
            /\ cState \in {"init", "collecting", "committed", "aborted"}
            /\ yesVotes \subseteq Participants
            /\ noVotes \subseteq Participants
            /\ prepSent \subseteq Participants

        \* Safety: no participant committed while another aborted
        Consistency ==
            \A p1, p2 \in Participants :
                ~ (pState[p1] = "committed" /\ pState[p2] = "aborted")

        \* Validity: commit requires unanimous yes votes
        CommitValidity ==
            (\E p \in Participants : pState[p] = "committed") =>
                (noVotes = {})
    }

    fair process (Coordinator = "coord")
    variables toSend = {};
    {
        C1:
            cState := "collecting";
            toSend := Participants;
        C1a:
            while (toSend /= {}) {
                with (p \in toSend) {
                    prepSent := prepSent \union {p};
                    toSend := toSend \ {p};
                };
            };
        C2:
            await (yesVotes \union noVotes) = Participants;
            if (Cardinality(noVotes) < Cardinality(Participants)) {
                cState := "committed";
            } else {
                cState := "aborted";
            };
        C3:
            toSend := Participants;
        C3a:
            while (toSend /= {}) {
                with (p \in toSend) {
                    decisionSent := decisionSent \union {<<p, cState>>};
                    toSend := toSend \ {p};
                };
            };
    }

    fair process (Part \in Participants)
    {
        P1:
            await self \in prepSent;
            either {
                pState[self] := "prepared";
                yesVotes := yesVotes \union {self};
            } or {
                pState[self] := "aborted";
                noVotes := noVotes \union {self};
            };
        P2:
            either {
                await <<self, "committed">> \in decisionSent;
                pState[self] := "committed";
            } or {
                await <<self, "aborted">> \in decisionSent;
                pState[self] := "aborted";
            } or {
                pState[self] := "aborted";
            };
    }
}
*)
====
