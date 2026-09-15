#!/usr/bin/env python3
"""
Fix bugs in the TLA+ commit protocol specification and extend with
coordinator crash recovery and liveness verification.

"""

import subprocess
import json
import os
import sys

TLA_TOOLS = "/app/tools/tla2tools.jar"

def run_tlc(tla_file, cfg_file):
    """Translate PlusCal and run TLC. Returns (success, output)."""
    workdir = os.path.dirname(os.path.abspath(tla_file))
    tla_base = os.path.basename(tla_file)
    cfg_base = os.path.basename(cfg_file)
    module = tla_base.replace(".tla", "")

    # Translate PlusCal
    result = subprocess.run(
        ["java", "-Xmx512m", "-cp", TLA_TOOLS, "pcal.trans", tla_base],
        capture_output=True, text=True, timeout=60, cwd=workdir
    )
    print(f"PlusCal translator output for {tla_base}:")
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    # Run TLC
    result = subprocess.run(
        ["java", "-Xmx512m", "-cp", TLA_TOOLS, "tlc2.TLC",
         "-config", cfg_base, module, "-workers", "1"],
        capture_output=True, text=True, timeout=300, cwd=workdir
    )
    output = result.stdout + "\n" + result.stderr
    print(f"TLC output for {module}:")
    print(output)

    passed = "Model checking completed. No error has been found." in output
    return passed, output


# ==========================================================================
# Step 1: Write the FIXED specification
# ==========================================================================
# Bug 1: Coordinator commits unless ALL voted no (should commit only if NONE
#         voted no). The condition `Cardinality(noVotes) < Cardinality(Participants)`
#         is wrong; it should be `noVotes = {}`.
# Bug 2: Participant P2 has a third `either/or` branch that lets any
#         participant unilaterally abort even after voting yes, breaking the
#         commit agreement.

FIXED_SPEC = r"""---- MODULE commit_protocol_fixed ----
EXTENDS Integers, FiniteSets, TLC

CONSTANTS Participants

(* --algorithm TwoPhaseCommitFixed {
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

        Consistency ==
            \A p1, p2 \in Participants :
                ~ (pState[p1] = "committed" /\ pState[p2] = "aborted")

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
            if (noVotes = {}) {
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
            };
    }
}
*)
====
"""

FIXED_CFG = """SPECIFICATION Spec
CONSTANT Participants = {p1, p2, p3}
INVARIANT TypeOK
INVARIANT Consistency
INVARIANT CommitValidity
"""


# ==========================================================================
# Step 2: Write the RECOVERY specification
# ==========================================================================
# Extends the fixed spec with:
# - coordCrashed variable modeling coordinator failure after decision
# - coordFinished variable signaling normal coordinator completion
# - Non-deterministic crash point after the coordinator decides
# - A Recovery process that activates on crash and relays the decision
# - Liveness temporal property: all participants eventually terminate
#
# Key design: the Recovery process waits for coordCrashed OR coordFinished
# (NOT AllTerminated, which can become true prematurely when no-voters
# have pState="aborted" from P1 before reaching P2).

RECOVERY_SPEC = r"""---- MODULE commit_protocol_recovery ----
EXTENDS Integers, FiniteSets, TLC

CONSTANTS Participants

(* --algorithm TwoPhaseCommitRecovery {
    variables
        pState = [p \in Participants |-> "working"],
        cState = "init",
        yesVotes = {},
        noVotes = {},
        prepSent = {},
        decisionSent = {},
        coordCrashed = FALSE,
        coordFinished = FALSE;

    define {
        TypeOK ==
            /\ pState \in [Participants -> {"working", "prepared", "committed", "aborted"}]
            /\ cState \in {"init", "collecting", "committed", "aborted"}
            /\ yesVotes \subseteq Participants
            /\ noVotes \subseteq Participants
            /\ prepSent \subseteq Participants
            /\ coordCrashed \in BOOLEAN
            /\ coordFinished \in BOOLEAN

        Consistency ==
            \A p1, p2 \in Participants :
                ~ (pState[p1] = "committed" /\ pState[p2] = "aborted")

        CommitValidity ==
            (\E p \in Participants : pState[p] = "committed") =>
                (noVotes = {})

        AllTerminated ==
            \A p \in Participants : pState[p] \in {"committed", "aborted"}

        Liveness == <>(AllTerminated)
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
            if (noVotes = {}) {
                cState := "committed";
            } else {
                cState := "aborted";
            };
        C2crash:
            either {
                skip;
            } or {
                coordCrashed := TRUE;
            };
        C3:
            if (~coordCrashed) {
                toSend := Participants;
            };
        C3a:
            while (toSend /= {}) {
                with (p \in toSend) {
                    decisionSent := decisionSent \union {<<p, cState>>};
                    toSend := toSend \ {p};
                };
            };
        C4:
            if (~coordCrashed) {
                coordFinished := TRUE;
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
            };
    }

    fair process (Recovery = "recovery")
    variables toSendR = {};
    {
        R1:
            await coordCrashed \/ coordFinished;
            if (coordCrashed) {
                toSendR := Participants;
            };
        R2:
            while (toSendR /= {}) {
                with (p \in toSendR) {
                    decisionSent := decisionSent \union {<<p, cState>>};
                    toSendR := toSendR \ {p};
                };
            };
    }
}
*)
====
"""

RECOVERY_CFG = """SPECIFICATION Spec
CONSTANT Participants = {p1, p2, p3}
INVARIANT TypeOK
INVARIANT Consistency
INVARIANT CommitValidity
PROPERTY Liveness
"""


# ==========================================================================
# Main: write files, verify with TLC, produce analysis
# ==========================================================================

def main():
    os.chdir("/app")

    # Write fixed spec and config
    with open("/app/commit_protocol_fixed.tla", "w") as f:
        f.write(FIXED_SPEC.strip() + "\n")
    with open("/app/commit_protocol_fixed.cfg", "w") as f:
        f.write(FIXED_CFG.strip() + "\n")

    # Verify fixed spec
    print("=" * 60)
    print("Verifying fixed specification...")
    print("=" * 60)
    ok, out = run_tlc("/app/commit_protocol_fixed.tla",
                      "/app/commit_protocol_fixed.cfg")
    if not ok:
        print("FAILED: Fixed spec did not pass TLC", file=sys.stderr)
        sys.exit(1)
    print("PASSED: Fixed spec verified.\n")

    # Write recovery spec and config
    with open("/app/commit_protocol_recovery.tla", "w") as f:
        f.write(RECOVERY_SPEC.strip() + "\n")
    with open("/app/commit_protocol_recovery.cfg", "w") as f:
        f.write(RECOVERY_CFG.strip() + "\n")

    # Verify recovery spec
    print("=" * 60)
    print("Verifying recovery specification...")
    print("=" * 60)
    ok, out = run_tlc("/app/commit_protocol_recovery.tla",
                      "/app/commit_protocol_recovery.cfg")
    if not ok:
        print("FAILED: Recovery spec did not pass TLC", file=sys.stderr)
        sys.exit(1)
    print("PASSED: Recovery spec verified.\n")

    # Write analysis
    analysis = {
        "bugs": [
            {
                "id": 1,
                "description": (
                    "The coordinator's commit condition in step C2 uses "
                    "'Cardinality(noVotes) < Cardinality(Participants)', which "
                    "commits the transaction as long as at least one participant "
                    "voted yes. This allows committing even when some participants "
                    "voted no, violating the unanimity requirement."
                ),
                "fix": (
                    "Changed the condition to 'noVotes = {}' so the coordinator "
                    "only commits when no participant voted to abort."
                ),
                "invariant_violated": "CommitValidity"
            },
            {
                "id": 2,
                "description": (
                    "The participant process P2 has a third 'either/or' branch "
                    "with no await guard that allows any participant to "
                    "unilaterally abort at any time, even after voting yes. "
                    "This breaks the commit agreement because the coordinator "
                    "may have already committed other participants based on "
                    "this participant's yes vote."
                ),
                "fix": (
                    "Removed the third unguarded branch from P2's either/or "
                    "block, so participants can only transition based on the "
                    "coordinator's decision message."
                ),
                "invariant_violated": "Consistency"
            }
        ],
        "recovery_mechanism": (
            "Added a Recovery process that monitors for coordinator crash or "
            "normal completion. The coordinator can non-deterministically crash "
            "at label C2crash after making its commit/abort decision but before "
            "broadcasting it. A coordFinished flag is set by the coordinator at "
            "the end of normal execution (label C4) to signal successful "
            "completion. The Recovery process awaits either coordCrashed or "
            "coordFinished. When coordCrashed becomes true, Recovery reads the "
            "coordinator's decision from cState and relays it to all "
            "participants via decisionSent. If the coordinator completes "
            "normally (coordFinished is true), Recovery activates but takes "
            "no action since decisions were already delivered."
        ),
        "liveness_property": (
            "<>(AllTerminated) where AllTerminated == "
            "\\A p \\in Participants : pState[p] \\in {\"committed\", \"aborted\"}. "
            "This temporal property ensures every participant eventually "
            "reaches a terminal state, verified under weak fairness."
        )
    }

    with open("/app/analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)
    print("Analysis written to /app/analysis.json")


if __name__ == "__main__":
    main()
